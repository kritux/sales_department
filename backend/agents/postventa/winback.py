"""
WinBack agent — re-engages leads after 90-day cooling-off period.

Trigger: lead.status == 'no_response' AND days since last_contact_at >= 90.

Action: Send one re-engagement email. If the lead responds → status='responded'
(set by caller / Supabase webhook). If still no response after 7 more days →
status='closed_lost' (set by next WinBack run that finds the lead still
no_response with last_contact_at ≥ 97 days ago).

Design:
  - get_winback_candidates() is a pure filter — no side effects.
  - run_winback() executes sends and returns desired mutations.
  - Caller (Director / scheduler) applies DB updates from WinbackResult.

Phase 5: candidate selection will be a Supabase query. For now, candidates
  are passed in from the calling code (Director reads Supabase, passes list).

Constants:
  _WINBACK_WAIT_DAYS = 90   — days since last_contact_at to qualify
  _CLOSE_LOST_DAYS   = 97   — 90-day wait + 7-day final window

Public API:
    get_winback_candidates(leads, wait_days, now)  -> List[Lead]
    run_winback(leads, tenant_config, dry_run, now) -> WinbackResult
    build_winback_agent(tenant_config)              -> crewai.Agent
"""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Literal, Optional

from pydantic import BaseModel

from config.settings import settings
from config.tenants import TenantConfig
from db.models import Lead
from tools.email_tool import send_email
from tools.rag_query import query_rag

if TYPE_CHECKING:
    from crewai import Agent

logger = logging.getLogger(__name__)

_WINBACK_WAIT_DAYS = 90   # days since last_contact_at before retry
_CLOSE_LOST_DAYS = 97     # 90 + 7-day final window before closing

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class LeadWinbackResult(BaseModel):
    lead_id: str
    action: Literal["email_sent", "close_lost_marked", "skipped", "error"]
    reason: str = ""
    mark_status: Optional[str] = None  # caller updates lead.status if set


class WinbackResult(BaseModel):
    tenant_id: str
    candidates_found: int = 0
    emails_sent: int = 0
    close_lost_marked: int = 0
    results: List[LeadWinbackResult] = []


# ---------------------------------------------------------------------------
# Re-engagement email template
# ---------------------------------------------------------------------------


def _render_winback_email(lead: Lead, tenant_config: TenantConfig, rag_context: str) -> tuple:
    """
    Render the WinBack re-engagement email.

    Different from the intro cadence — warmer tone, acknowledges time passed,
    offers something new (updated services / pricing from RAG if available).
    """
    lang = tenant_config.language
    value_block = rag_context if rag_context else (
        f"We've added new services and improved our offering for "
        f"{lead.category} companies like yours."
    )
    if lang == "es":
        subject = f"¿Seguimos en contacto? — {lead.company_name}"
        body = (
            f"Hola,\n\n"
            f"Han pasado unos meses desde que hablamos por primera vez. "
            f"Quería retomar el contacto con {lead.company_name}.\n\n"
            f"{value_block}\n\n"
            f"¿Sería buen momento para una llamada rápida?\n\n"
            f"Saludos,\n{tenant_config.sender_name}"
        )
    else:
        subject = f"Checking back in — {lead.company_name}"
        body = (
            f"Hi,\n\n"
            f"It's been a few months since I first reached out. "
            f"I wanted to check back in with {lead.company_name}.\n\n"
            f"{value_block}\n\n"
            f"Would now be a better time for a quick call?\n\n"
            f"Best,\n{tenant_config.sender_name}"
        )
    return subject, body


# ---------------------------------------------------------------------------
# Core logic (pure functions)
# ---------------------------------------------------------------------------


def get_winback_candidates(
    leads: List[Lead],
    wait_days: int = _WINBACK_WAIT_DAYS,
    now: Optional[datetime] = None,
) -> List[Lead]:
    """
    Filter leads eligible for WinBack re-engagement.

    Criteria:
      - status == 'no_response'
      - last_contact_at is set and >= wait_days ago
      - last_contact_at < (now - close_lost threshold) — not yet closed lost

    Returns leads sorted by score descending.
    """
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=wait_days)
    close_cutoff = now - timedelta(days=_CLOSE_LOST_DAYS)

    candidates = []
    for lead in leads:
        if lead.status != "no_response":
            continue
        if lead.last_contact_at is None:
            continue
        last = lead.last_contact_at
        if last > cutoff:
            continue  # too recent
        if last <= close_cutoff:
            continue  # past close-lost window (will be closed separately)
        candidates.append(lead)

    return sorted(candidates, key=lambda l: l.score, reverse=True)


def get_close_lost_candidates(
    leads: List[Lead],
    now: Optional[datetime] = None,
) -> List[Lead]:
    """
    Return no_response leads that have been silent for > _CLOSE_LOST_DAYS.

    These should be moved to status='closed_lost' by the caller.
    """
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=_CLOSE_LOST_DAYS)
    return [
        l for l in leads
        if l.status == "no_response"
        and l.last_contact_at is not None
        and l.last_contact_at <= cutoff
    ]


# ---------------------------------------------------------------------------
# Public API — run_winback
# ---------------------------------------------------------------------------


def run_winback(
    leads: List[Lead],
    tenant_config: TenantConfig,
    dry_run: Optional[bool] = None,
    now: Optional[datetime] = None,
) -> WinbackResult:
    """
    Re-engage qualifying no_response leads and mark overdue ones as closed_lost.

    Args:
        leads:         Full list of tenant leads (or pre-filtered by caller).
        tenant_config: Provides sender identity and DRY_RUN gate.
        dry_run:       True → no real sends. None → settings.dry_run.
        now:           Override current time (for testing).

    Returns:
        WinbackResult with per-lead actions and aggregate counts.
        Caller applies mark_status values to the database.
    """
    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run
    now = now or datetime.utcnow()

    run = WinbackResult(tenant_id=tenant_config.tenant_id)

    # First, mark overdue leads as closed_lost
    for lead in get_close_lost_candidates(leads, now=now):
        run.close_lost_marked += 1
        run.results.append(LeadWinbackResult(
            lead_id=lead.id,
            action="close_lost_marked",
            reason=f"no response for >{_CLOSE_LOST_DAYS} days",
            mark_status="closed_lost",
        ))

    # Then, re-engage winback candidates
    candidates = get_winback_candidates(leads, now=now)
    run.candidates_found = len(candidates)

    for lead in candidates:
        # Fetch RAG context (best-effort)
        rag_context = ""
        try:
            resp = query_rag(
                tenant_id=tenant_config.tenant_id,
                query=f"{lead.company_name} {lead.category} services",
                top_k=3,
            )
            rag_context = resp.context if resp.found else ""
        except Exception:
            pass

        subject, body = _render_winback_email(lead, tenant_config, rag_context)

        try:
            send_email(
                lead=lead,
                tenant_config=tenant_config,
                subject=subject,
                body=body,
                dry_run=is_dry_run,
            )
            logger.info(
                "winback: re-engagement email sent | tenant=%s | lead=%s",
                tenant_config.tenant_id, lead.id,
            )
            run.emails_sent += 1
            run.results.append(LeadWinbackResult(
                lead_id=lead.id,
                action="email_sent",
                mark_status="contacted",
            ))
        except Exception as exc:
            logger.error(
                "winback: email failed | lead=%s | error=%s", lead.id, exc,
            )
            run.results.append(LeadWinbackResult(
                lead_id=lead.id,
                action="error",
                reason=str(exc),
            ))

    return run


# ---------------------------------------------------------------------------
# Public API — build_winback_agent (CrewAI wrapper)
# ---------------------------------------------------------------------------


def build_winback_agent(tenant_config: TenantConfig) -> "Agent":
    """
    Build a CrewAI Agent that handles WinBack re-engagement.

    Args:
        tenant_config: Fully populated TenantConfig.

    Returns:
        CrewAI Agent configured as WinBack Specialist.
    """
    from crewai import Agent  # lazy
    from langchain.tools import tool  # lazy
    from langchain_anthropic import ChatAnthropic  # lazy

    tc = tenant_config

    @tool("run_winback_campaign")
    def run_winback_campaign(lead_ids_json: str) -> str:
        """
        Run the WinBack re-engagement campaign for a JSON list of lead IDs.
        Returns a JSON summary of emails sent and leads closed.
        """
        import json as _json
        try:
            lead_ids = _json.loads(lead_ids_json)
        except Exception:
            return _json.dumps({"error": "invalid JSON for lead_ids"})
        return _json.dumps({
            "note": "Lead fetch from Supabase required (Phase 5)",
            "lead_ids": lead_ids,
        })

    haiku = ChatAnthropic(model="claude-haiku-20240307")

    return Agent(
        role="WinBack Specialist",
        goal=(
            f"Re-engage dormant leads for {tenant_config.company_name} "
            f"that went silent after the initial outreach sequence. "
            f"Identify which ones are worth a second attempt after 90 days."
        ),
        backstory=(
            f"You are {tenant_config.sender_name} from "
            f"{tenant_config.company_name}. You specialize in warming up "
            f"leads that have gone cold — crafting genuine, non-pushy "
            f"re-engagement messages that respect the prospect's time."
        ),
        llm=haiku,
        tools=[run_winback_campaign],
        verbose=True,
        allow_delegation=False,
    )
