"""
Strategic lead cadence — email + call sequence over 14 days.

Cadence schedule (4 touchpoints):
  Step 1 — Day  0: Email intro     (first contact, status → 'contacted')
  Step 2 — Day  3: Email value     (follow-up value proposition)
  Step 3 — Day  7: Prospect call   (voice outreach via call_tool.call_prospect)
  Step 4 — Day 14: Email final     (last-chance email)

Sequence control:
  - Any response (status ∉ {'new', 'contacted'}) halts the sequence immediately.
  - After all 4 steps complete with no response → mark_status='no_response'.
  - Caller (Director / scheduler) applies DB updates; this module is stateless
    w.r.t. persistence — it returns desired mutations in LeadCadenceResult.
  - Daily contact cap: tenant_config.daily_contact_cap (emails + calls combined).
    run_email_cadence() accepts daily_sent_count to carry over prior contacts.

Cadence state persistence:
  - Stored as the first line of lead.notes: CADENCE:{json}
  - _parse_cadence_state() reads it; _encode_cadence_state() writes it.
  - Phase 5 (Supabase) will move this to a dedicated cadence_state table.

WinBack: after status='no_response', handled by agents/postventa/winback.py
  after a 90-day wait.

Public API:
    get_next_cadence_step(lead, state, now)  -> Optional[CadenceStep]
    should_mark_no_response(lead, state)     -> bool
    run_email_cadence(leads, tenant_config, daily_sent_count, dry_run, now)
                                             -> CadenceRunResult
    build_email_agent(tenant_config)         -> crewai.Agent
"""

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Literal, Optional

from pydantic import BaseModel

from config.settings import settings
from config.tenants import TenantConfig
from db.models import Lead
from tools.email_tool import OutboundMessage, render_email, send_email
from tools.call_tool import call_prospect
from tools.rag_query import query_rag

if TYPE_CHECKING:
    from crewai import Agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = frozenset({"new", "contacted"})
_CADENCE_NOTES_KEY = "CADENCE:"
_TOTAL_STEPS = 4

# Each entry: (step_number, day_offset_from_first_contact, channel, template_key)
_CADENCE_SCHEDULE: List[dict] = [
    {"step": 1, "day": 0,  "channel": "email", "template": "intro"},
    {"step": 2, "day": 3,  "channel": "email", "template": "value"},
    {"step": 3, "day": 7,  "channel": "call",  "template": "followup"},
    {"step": 4, "day": 14, "channel": "email", "template": "final"},
]

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class CadenceStep(BaseModel):
    step: int
    day: int
    channel: Literal["email", "call"]
    template: str


class CadenceState(BaseModel):
    """Tracks sequence progress. Serialized to lead.notes."""
    first_contact_at: datetime
    last_step_completed: int = 0  # 0 = intro not yet sent


class LeadCadenceResult(BaseModel):
    lead_id: str
    action: Literal[
        "email_sent",
        "call_made",
        "no_response_marked",
        "halted",
        "skipped",
        "cap_reached",
        "error",
    ]
    step: int = 0
    channel: str = ""
    reason: str = ""
    updated_notes: Optional[str] = None  # caller persists to DB
    mark_status: Optional[str] = None    # caller updates lead.status if set


class CadenceRunResult(BaseModel):
    tenant_id: str
    processed: int = 0
    emails_sent: int = 0
    calls_made: int = 0
    no_response_marked: int = 0
    cap_reached: bool = False
    results: List[LeadCadenceResult] = []


# ---------------------------------------------------------------------------
# Cadence state helpers
# ---------------------------------------------------------------------------


def _parse_cadence_state(lead: Lead) -> Optional[CadenceState]:
    """
    Extract CadenceState from lead.notes.

    Notes format: first line is CADENCE:{json}, rest is free text.
    Returns None if the lead has never been contacted via the cadence.
    """
    notes = lead.notes or ""
    first_line = notes.split("\n")[0]
    if not first_line.startswith(_CADENCE_NOTES_KEY):
        return None
    try:
        raw = json.loads(first_line[len(_CADENCE_NOTES_KEY):])
        return CadenceState(**raw)
    except Exception:
        return None


def _encode_cadence_state(state: CadenceState, existing_notes: str = "") -> str:
    """
    Write CadenceState as the first line of notes.

    Replaces any existing CADENCE: line; preserves the rest of the notes.
    """
    json_str = state.model_dump_json()
    new_first_line = f"{_CADENCE_NOTES_KEY}{json_str}"
    lines = existing_notes.splitlines()
    rest_lines = [l for l in lines if not l.startswith(_CADENCE_NOTES_KEY)]
    rest = "\n".join(rest_lines).strip()
    return f"{new_first_line}\n{rest}".strip() if rest else new_first_line


# ---------------------------------------------------------------------------
# Email templates for follow-up steps
# ---------------------------------------------------------------------------


def _render_value_email(
    lead: Lead,
    tenant_config: TenantConfig,
    rag_context: str,
) -> tuple:
    """Step 2 — value proposition follow-up."""
    lang = tenant_config.language
    value_block = rag_context if rag_context else (
        f"We've helped similar {lead.category} companies in {lead.city} "
        f"generate more leads and win better contracts."
    )
    if lang == "es":
        subject = f"Siguiendo up — {lead.company_name}"
        body = (
            f"Hola,\n\n"
            f"Le escribo de nuevo desde {tenant_config.company_name}. "
            f"Quería compartir cómo hemos ayudado a negocios similares:\n\n"
            f"{value_block}\n\n"
            f"¿Le interesaría una llamada de 15 minutos esta semana?\n\n"
            f"Saludos,\n{tenant_config.sender_name}"
        )
    else:
        subject = f"Following up — {lead.company_name}"
        body = (
            f"Hi,\n\n"
            f"Following up from {tenant_config.company_name}. "
            f"I wanted to share a bit more about the results we've driven:\n\n"
            f"{value_block}\n\n"
            f"Would a 15-minute call this week work for you?\n\n"
            f"Best,\n{tenant_config.sender_name}"
        )
    return subject, body


def _render_final_email(
    lead: Lead,
    tenant_config: TenantConfig,
) -> tuple:
    """Step 4 — last-chance email, no RAG needed (brief closing)."""
    lang = tenant_config.language
    if lang == "es":
        subject = f"Último intento — {lead.company_name}"
        body = (
            f"Hola,\n\n"
            f"Entiendo que está ocupado. Este es mi último mensaje por ahora.\n\n"
            f"Si alguna vez necesita apoyo de ventas para {lead.company_name}, "
            f"no dude en contactarme.\n\n"
            f"¡Mucho éxito!\n{tenant_config.sender_name}"
        )
    else:
        subject = f"Last note — {lead.company_name}"
        body = (
            f"Hi,\n\n"
            f"I understand you're busy — this is my last message for now.\n\n"
            f"If you ever need sales support for {lead.company_name}, "
            f"I'd love to reconnect.\n\n"
            f"Wishing you success!\n{tenant_config.sender_name}"
        )
    return subject, body


def _render_for_step(
    step: CadenceStep,
    lead: Lead,
    tenant_config: TenantConfig,
    rag_context: str,
) -> tuple:
    """Dispatch to the right template based on step."""
    if step.template == "intro":
        return render_email(lead, tenant_config, rag_context)
    if step.template == "value":
        return _render_value_email(lead, tenant_config, rag_context)
    if step.template == "final":
        return _render_final_email(lead, tenant_config)
    return render_email(lead, tenant_config, rag_context)


# ---------------------------------------------------------------------------
# Core cadence logic (pure functions)
# ---------------------------------------------------------------------------


def get_next_cadence_step(
    lead: Lead,
    state: Optional[CadenceState],
    now: datetime,
) -> Optional[CadenceStep]:
    """
    Return the next CadenceStep that is due for this lead, or None.

    None means one of:
      - Lead has responded / reached a terminal status (sequence halted).
      - All 4 steps are complete (caller should check should_mark_no_response).
      - No step is due yet (called before the next day threshold).
    """
    if lead.status not in _ACTIVE_STATUSES:
        return None

    if state is None:
        # Never contacted — step 1 is always due immediately.
        return CadenceStep(**_CADENCE_SCHEDULE[0])

    days_elapsed = (now - state.first_contact_at).days

    for raw in _CADENCE_SCHEDULE:
        if raw["step"] <= state.last_step_completed:
            continue  # already done
        if days_elapsed >= raw["day"]:
            return CadenceStep(**raw)

    return None  # either not due yet, or all 4 done


def should_mark_no_response(
    lead: Lead,
    state: Optional[CadenceState],
) -> bool:
    """
    Return True when all 4 steps are done and the lead still hasn't responded.

    The caller should update lead.status = 'no_response'.
    """
    if lead.status not in _ACTIVE_STATUSES:
        return False
    if state is None:
        return False
    return state.last_step_completed >= _TOTAL_STEPS


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def _fetch_rag(tenant_id: str, lead: Lead) -> str:
    """Query RAG for context; returns '' on any failure."""
    try:
        resp = query_rag(
            tenant_id=tenant_id,
            query=f"{lead.company_name} {lead.category} services pricing",
            top_k=3,
        )
        return resp.context if resp.found else ""
    except Exception:
        return ""


def _execute_step(
    step: CadenceStep,
    lead: Lead,
    tenant_config: TenantConfig,
    now: datetime,
    dry_run: bool,
) -> LeadCadenceResult:
    """Execute one cadence step and return the result with updated state."""
    rag_context = _fetch_rag(tenant_config.tenant_id, lead) if step.channel == "email" else ""

    # Build updated CadenceState
    old_state = _parse_cadence_state(lead)
    if old_state is None:
        new_state = CadenceState(first_contact_at=now, last_step_completed=step.step)
    else:
        new_state = CadenceState(
            first_contact_at=old_state.first_contact_at,
            last_step_completed=step.step,
        )
    updated_notes = _encode_cadence_state(new_state, lead.notes)

    mark_status = "contacted" if lead.status == "new" else None

    if step.channel == "email":
        subject, body = _render_for_step(step, lead, tenant_config, rag_context)
        try:
            send_email(
                lead=lead,
                tenant_config=tenant_config,
                subject=subject,
                body=body,
                dry_run=dry_run,
            )
            logger.info(
                "email_agent: step %d sent | tenant=%s | lead=%s",
                step.step, tenant_config.tenant_id, lead.id,
            )
            return LeadCadenceResult(
                lead_id=lead.id,
                action="email_sent",
                step=step.step,
                channel="email",
                updated_notes=updated_notes,
                mark_status=mark_status,
            )
        except Exception as exc:
            logger.error(
                "email_agent: step %d email failed | lead=%s | error=%s",
                step.step, lead.id, exc,
            )
            return LeadCadenceResult(
                lead_id=lead.id,
                action="error",
                step=step.step,
                channel="email",
                reason=str(exc),
            )

    else:  # call
        if not lead.phone:
            logger.warning(
                "email_agent: step %d skipped (no phone) | lead=%s",
                step.step, lead.id,
            )
            return LeadCadenceResult(
                lead_id=lead.id,
                action="skipped",
                step=step.step,
                channel="call",
                reason="no phone number",
                updated_notes=updated_notes,
                mark_status=mark_status,
            )
        try:
            call_prospect(lead=lead, tenant_config=tenant_config, dry_run=dry_run)
            logger.info(
                "email_agent: step %d call made | tenant=%s | lead=%s",
                step.step, tenant_config.tenant_id, lead.id,
            )
            return LeadCadenceResult(
                lead_id=lead.id,
                action="call_made",
                step=step.step,
                channel="call",
                updated_notes=updated_notes,
                mark_status=mark_status,
            )
        except Exception as exc:
            logger.error(
                "email_agent: step %d call failed | lead=%s | error=%s",
                step.step, lead.id, exc,
            )
            return LeadCadenceResult(
                lead_id=lead.id,
                action="error",
                step=step.step,
                channel="call",
                reason=str(exc),
            )


# ---------------------------------------------------------------------------
# Public API — run_email_cadence
# ---------------------------------------------------------------------------


def run_email_cadence(
    leads: List[Lead],
    tenant_config: TenantConfig,
    daily_sent_count: int = 0,
    dry_run: Optional[bool] = None,
    now: Optional[datetime] = None,
) -> CadenceRunResult:
    """
    Process all leads and execute any cadence steps that are due today.

    Args:
        leads:            List of Lead objects (sorted by score desc recommended).
        tenant_config:    Provides identity, cap, and DRY_RUN gate.
        daily_sent_count: Contacts already sent today (carry-over from prior runs).
        dry_run:          True → no real sends. None → settings.dry_run.
        now:              Override current time (for testing).

    Returns:
        CadenceRunResult with per-lead results and aggregate counts.
    """
    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run
    now = now or datetime.utcnow()
    cap = tenant_config.daily_contact_cap

    run = CadenceRunResult(tenant_id=tenant_config.tenant_id)
    sent_today = daily_sent_count

    for lead in leads:
        run.processed += 1

        if sent_today >= cap:
            run.cap_reached = True
            run.results.append(LeadCadenceResult(
                lead_id=lead.id,
                action="cap_reached",
                reason=f"daily cap of {cap} reached",
            ))
            continue

        # Terminal / halted
        if lead.status not in _ACTIVE_STATUSES:
            run.results.append(LeadCadenceResult(
                lead_id=lead.id,
                action="halted",
                reason=f"status={lead.status!r}",
            ))
            continue

        state = _parse_cadence_state(lead)

        # Mark no_response if all steps done
        if should_mark_no_response(lead, state):
            run.no_response_marked += 1
            run.results.append(LeadCadenceResult(
                lead_id=lead.id,
                action="no_response_marked",
                mark_status="no_response",
                reason="all 4 cadence steps completed with no reply",
            ))
            continue

        step = get_next_cadence_step(lead, state, now)
        if step is None:
            run.results.append(LeadCadenceResult(
                lead_id=lead.id,
                action="skipped",
                reason="no step due yet",
            ))
            continue

        result = _execute_step(step, lead, tenant_config, now, is_dry_run)
        run.results.append(result)

        if result.action == "email_sent":
            run.emails_sent += 1
            sent_today += 1
        elif result.action == "call_made":
            run.calls_made += 1
            sent_today += 1

    return run


# ---------------------------------------------------------------------------
# Public API — build_email_agent (CrewAI wrapper)
# ---------------------------------------------------------------------------


def build_email_agent(tenant_config: TenantConfig) -> "Agent":
    """
    Build a CrewAI Agent that manages the 4-step outbound cadence.

    The agent can be delegated a list of lead IDs by the Director, and
    calls run_email_cadence() to process them.

    Args:
        tenant_config: Fully populated TenantConfig.

    Returns:
        CrewAI Agent configured as Email Specialist.
    """
    from crewai import Agent  # lazy
    from langchain.tools import tool  # lazy
    from langchain_anthropic import ChatAnthropic  # lazy

    tc = tenant_config

    @tool("run_outbound_cadence")
    def run_outbound_cadence(lead_ids_json: str) -> str:
        """
        Run the 4-step outbound cadence for a JSON list of lead IDs.
        Returns a JSON summary of emails sent, calls made, and no-response markings.
        """
        import json as _json
        try:
            lead_ids = _json.loads(lead_ids_json)
        except Exception:
            return _json.dumps({"error": "invalid JSON for lead_ids"})

        # Phase 5: fetch leads from Supabase by ID.
        # For now return a stub result.
        return _json.dumps({
            "note": "Lead fetch from Supabase required (Phase 5)",
            "lead_ids": lead_ids,
        })

    haiku = ChatAnthropic(model="claude-haiku-20240307")

    return Agent(
        role="Email Specialist",
        goal=(
            f"Run the 4-step outbound email and call cadence for "
            f"{tenant_config.company_name}. "
            f"Maximize responses while respecting the daily contact cap "
            f"of {tenant_config.daily_contact_cap} contacts per day."
        ),
        backstory=(
            f"You are {tenant_config.sender_name}, a skilled outbound "
            f"sales rep at {tenant_config.company_name}. You follow a "
            f"disciplined 4-step cadence over 14 days and respect every "
            f"response — halting immediately when a prospect replies."
        ),
        llm=haiku,
        tools=[run_outbound_cadence],
        verbose=True,
        allow_delegation=False,
    )
