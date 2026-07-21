"""
CrewAI Director — hierarchical crew orchestrating the daily sales run.

Agent hierarchy (TEAM.md):
  Director (Claude Sonnet) — strategic decisions, allow_delegation=True
    ├── Prospection Manager (Haiku) — finds and qualifies leads
    ├── Sales Closer Manager (Haiku) — outreach and conversion
    └── Post-Sale Manager (Haiku) — meetings, follow-ups, reactivation

Execution flow:
  run_daily(tenant_config)
    1. _build_agents()         — instantiate four CrewAI Agent objects
    2. build_daily_tasks()     — Task list with context chaining (jobs.py)
    3. _build_crew()           — Process.hierarchical, manager=director
    4. crew.kickoff()          — run the full pipeline
    5. end_of_day_sequence()   — WhatsApp summary + 15-min voice escalation

All crewai / langchain imports are lazy so this module loads cleanly
in dry-run and test contexts.

Public API:
    build_director_crew(tenant_config, tasks=None)  -> Crew
    run_daily(tenant_config, dry_run=None)          -> str
    end_of_day_sequence(tenant_config, summary, dry_run=None, _wa_wait_seconds=900)
"""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from pydantic import BaseModel

from config.settings import settings
from config.tenants import TenantConfig
from tools.call_tool import alert_owner_by_voice
from tools.whatsapp_tool import is_whatsapp_read, send_whatsapp_summary

if TYPE_CHECKING:
    from crewai import Agent, Crew  # type: ignore

_REPO_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------

class OutOfScopeOpportunity(BaseModel):
    session_id: str = ""
    company_name: str = ""
    contact_info: str = ""
    industry_mentioned: str = ""


class DailyReport(BaseModel):
    tenant_id: str
    date: str = ""
    leads_found: int = 0
    emails_sent: int = 0
    meetings_booked: int = 0
    out_of_scope_opportunities: List[OutOfScopeOpportunity] = []
    summary_text: str = ""


def format_whatsapp_summary(report: DailyReport) -> str:
    """
    Format a DailyReport into a WhatsApp-ready summary string.
    Out-of-scope opportunities are surfaced as a separate section
    so the owner can decide whether to pursue them personally.
    """
    lines = [report.summary_text] if report.summary_text else []
    if report.out_of_scope_opportunities:
        count = len(report.out_of_scope_opportunities)
        lines.append(f"\n⚠️ Out-of-scope opportunities ({count}):")
        for opp in report.out_of_scope_opportunities:
            entry = f"  • {opp.company_name or 'Unknown'}"
            if opp.industry_mentioned:
                entry += f" [{opp.industry_mentioned}]"
            if opp.contact_info:
                entry += f" — {opp.contact_info}"
            lines.append(entry)
        lines.append("→ Review and decide whether to pursue.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def _build_agents(tenant_config: TenantConfig) -> Dict[str, "Agent"]:
    """
    Instantiate the four sales-team agents for this tenant.

    Returns a dict keyed by role slug:
        "director"     — Claude Sonnet, allow_delegation=True
        "prospeccion"  — Claude Haiku, lead scouting
        "cierre"       — Claude Haiku, outreach and conversion
        "postventa"    — Claude Haiku, follow-ups and meetings
    """
    from crewai import Agent  # lazy
    from langchain_anthropic import ChatAnthropic  # lazy

    haiku = ChatAnthropic(model="claude-haiku-20240307")
    sonnet = ChatAnthropic(model="claude-sonnet-20240229")

    criteria = tenant_config.lead_criteria

    director = Agent(
        role="Sales Director",
        goal=(
            f"Orchestrate the sales team for {tenant_config.company_name}. "
            f"Maximize qualified leads and meetings booked today. "
            f"Tenant: {tenant_config.tenant_id}."
        ),
        backstory=(
            "You are a senior sales director with 15 years experience running "
            "high-performance outbound sales teams. You delegate to your managers, "
            "review their outputs, and make final strategic decisions."
        ),
        llm=sonnet,
        verbose=True,
        allow_delegation=True,
    )

    prospeccion_manager = Agent(
        role="Prospection Manager",
        goal=(
            f"Find and qualify the best leads for {tenant_config.company_name}. "
            f"Target industries: {criteria.industries or ['any']}. "
            f"Exclude: {criteria.exclude_keywords or ['none']}. "
            f"Geographic center: {tenant_config.geo_center}."
        ),
        backstory=(
            "You run the prospection team. You decide which search keywords to use "
            "and which leads to pursue. You delegate scraping and scoring to scouts."
        ),
        llm=haiku,
        tools=[],
        verbose=True,
        allow_delegation=True,
    )

    cierre_manager = Agent(
        role="Sales Closer Manager",
        goal=(
            f"Convert qualified leads into meetings and deals for "
            f"{tenant_config.company_name}. "
            f"Language: {tenant_config.language}. "
            f"Sender: {tenant_config.sender_name} <{tenant_config.sender_email}>."
        ),
        backstory=(
            "You run the outreach team. You craft personalized cold emails using "
            "the RAG knowledge base, decide messaging strategy, and manage "
            "follow-up timing to maximize response rates."
        ),
        llm=haiku,
        tools=[],
        verbose=True,
        allow_delegation=True,
    )

    postventa_manager = Agent(
        role="Post-Sale Manager",
        goal=(
            "Book meetings, confirm quotes, and reactivate dormant leads. "
            "Ensure every interested prospect has a clear next step scheduled."
        ),
        backstory=(
            "You manage relationships after first contact. You follow up on "
            "leads that went quiet (no response in 14+ days), confirm pending "
            "meetings, and handle any post-meeting action items."
        ),
        llm=haiku,
        tools=[],
        verbose=True,
        allow_delegation=True,
    )

    return {
        "director": director,
        "prospeccion": prospeccion_manager,
        "cierre": cierre_manager,
        "postventa": postventa_manager,
    }


# ---------------------------------------------------------------------------
# Crew factory
# ---------------------------------------------------------------------------

def _build_crew(agents: Dict[str, "Agent"], tasks: List) -> "Crew":
    """
    Assemble a CrewAI hierarchical Crew with the Director as manager agent.

    Args:
        agents: Dict from _build_agents().
        tasks:  Ordered Task list from build_daily_tasks() in jobs.py.
    """
    from crewai import Crew, Process  # lazy

    return Crew(
        agents=list(agents.values()),
        tasks=tasks,
        process=Process.hierarchical,
        manager_agent=agents["director"],
        verbose=True,
    )


def build_director_crew(
    tenant_config: TenantConfig,
    tasks: Optional[List] = None,
) -> "Crew":
    """
    Build a ready-to-kickoff hierarchical Crew for the given tenant.

    Args:
        tenant_config: Fully populated TenantConfig.
        tasks:         Pre-built Task list. Pass [] to build crew without tasks
                       (tasks can be set later before kickoff).

    Returns:
        CrewAI Crew configured with Process.hierarchical.
    """
    agents = _build_agents(tenant_config)
    return _build_crew(agents, tasks if tasks is not None else [])


# ---------------------------------------------------------------------------
# End-of-day sequence: WhatsApp summary → voice escalation
# ---------------------------------------------------------------------------

def end_of_day_sequence(
    tenant_config: TenantConfig,
    report_summary: str,
    dry_run: Optional[bool] = None,
    _wa_wait_seconds: int = 900,
    daily_report: Optional[DailyReport] = None,
) -> None:
    """
    Send the daily WhatsApp summary; escalate to voice call if unread after wait.

    Called after crew.kickoff() completes. Runs synchronously — intended to
    execute inside an APScheduler background thread.

    Args:
        tenant_config:    Provides owner_whatsapp and owner_name for delivery.
        report_summary:   Plain-text summary from the crew's final task output.
        dry_run:          True → dry-run both WhatsApp and voice. None → settings.
        _wa_wait_seconds: Seconds to wait for read receipt before escalating.
                          Default 900 (15 min). Override to 0 in tests.
        daily_report:     Structured report; when provided its formatted summary
                          (including out-of-scope opportunities) is sent instead
                          of raw report_summary.
    """
    logger.info(
        "end_of_day_sequence | tenant=%s | dry_run=%s | wait=%ds",
        tenant_config.tenant_id, dry_run, _wa_wait_seconds,
    )

    wa_summary = (
        format_whatsapp_summary(daily_report)
        if daily_report is not None
        else report_summary
    )
    wa_msg = send_whatsapp_summary(tenant_config, wa_summary, dry_run=dry_run)
    logger.info(
        "WhatsApp result | tenant=%s | status=%s | sid=%s",
        tenant_config.tenant_id, wa_msg.status, wa_msg.message_id,
    )

    # Only escalate to voice if the message was actually delivered
    if wa_msg.status != "sent" or not wa_msg.message_id:
        logger.warning(
            "WhatsApp not delivered (status=%s) — skipping voice escalation | tenant=%s",
            wa_msg.status, tenant_config.tenant_id,
        )
        return

    logger.info(
        "Waiting %ds for WhatsApp read receipt | tenant=%s",
        _wa_wait_seconds, tenant_config.tenant_id,
    )
    time.sleep(_wa_wait_seconds)

    if not is_whatsapp_read(wa_msg.message_id, dry_run=dry_run):
        logger.info(
            "WhatsApp unread after %ds — escalating to voice | tenant=%s",
            _wa_wait_seconds, tenant_config.tenant_id,
        )
        alert_owner_by_voice(
            tenant_config,
            f"Your daily sales summary is ready. {report_summary}",
            dry_run=dry_run,
        )
    else:
        logger.info(
            "WhatsApp read — no voice escalation | tenant=%s",
            tenant_config.tenant_id,
        )


# ---------------------------------------------------------------------------
# Daily run entry point
# ---------------------------------------------------------------------------

def run_daily(
    tenant_config: TenantConfig,
    dry_run: Optional[bool] = None,
) -> str:
    """
    Full daily sales pipeline for one tenant.

    Steps:
      1. Build four agents (Director/Sonnet + 3 Managers/Haiku)
      2. Build ordered Task list with context chaining (from scheduler.jobs)
      3. Assemble hierarchical Crew
      4. crew.kickoff() — runs the pipeline
      5. end_of_day_sequence() — WhatsApp + voice escalation

    Args:
        tenant_config: Fully populated TenantConfig for this tenant.
        dry_run:       True → all tools operate in dry-run mode. None → settings.

    Returns:
        Crew kickoff result as a string (the Director's final summary).
    """
    from scheduler.jobs import build_daily_tasks  # late import avoids circular dep

    logger.info(
        "run_daily START | tenant=%s | dry_run=%s",
        tenant_config.tenant_id, dry_run,
    )

    agents = _build_agents(tenant_config)
    tasks = build_daily_tasks(tenant_config, agents)
    crew = _build_crew(agents, tasks)

    logger.info("crew.kickoff() | tenant=%s", tenant_config.tenant_id)
    result = crew.kickoff()
    result_str = str(result)

    logger.info(
        "run_daily DONE | tenant=%s | result_len=%d chars",
        tenant_config.tenant_id, len(result_str),
    )

    end_of_day_sequence(tenant_config, result_str, dry_run=dry_run)

    return result_str
