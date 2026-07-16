"""
Daily task builder for the CrewAI hierarchical crew.

Called by director.run_daily() to produce the ordered Task list.
Imported lazily inside run_daily() to avoid a circular import with director.py.

Task execution order:
    1. prospect_task  — Prospection Manager: scrape + qualify 50 leads
    2. outreach_task  — Sales Closer Manager: send personalized emails
                        (context: prospect_task)
    3. followup_task  — Post-Sale Manager: follow-ups + meeting confirmations
    4. report_task    — Director: compile DailyReport + save to DB
                        (context: all three previous tasks)

Public API:
    build_daily_tasks(tenant_config, agents) -> List[Task]
"""

import logging
from typing import TYPE_CHECKING, Dict, List

from config.tenants import TenantConfig

if TYPE_CHECKING:
    from crewai import Agent, Task  # type: ignore

logger = logging.getLogger(__name__)

_LEADS_TARGET = 50
_FOLLOWUP_DAYS = 14


def build_daily_tasks(
    tenant_config: TenantConfig,
    agents: Dict[str, "Agent"],
) -> List["Task"]:
    """
    Build the ordered Task list for one tenant's daily sales pipeline.

    Context chaining:
        outreach_task  depends on  prospect_task
        followup_task  (independent of outreach — runs in parallel intent)
        report_task    depends on  all three previous tasks

    Args:
        tenant_config: Fully populated TenantConfig for this tenant.
        agents:        Dict returned by director._build_agents():
                       keys "director", "prospeccion", "cierre", "postventa".

    Returns:
        Ordered list of 4 CrewAI Tasks ready to pass into Crew.kickoff().
    """
    from crewai import Task  # lazy — avoids hard dep at import time

    criteria = tenant_config.lead_criteria

    # ------------------------------------------------------------------
    # Task 1 — Prospecting
    # ------------------------------------------------------------------
    prospect_task = Task(
        description=(
            f"Find and qualify {_LEADS_TARGET} leads for "
            f"{tenant_config.company_name}.\n"
            f"Search keywords: {tenant_config.scraping_keywords}\n"
            f"Geographic center: {tenant_config.geo_center} "
            f"(radius: {tenant_config.geo_radius_miles} miles)\n"
            f"Lead criteria: {criteria.model_dump()}\n"
            "Save all qualified leads to the database with status='new'."
        ),
        agent=agents["prospeccion"],
        expected_output=(
            "JSON list of qualified lead IDs with scores, saved to database."
        ),
    )

    # ------------------------------------------------------------------
    # Task 2 — Outreach  (depends on prospecting)
    # ------------------------------------------------------------------
    outreach_task = Task(
        description=(
            f"Send personalized cold emails to all leads with status='new' "
            f"for tenant {tenant_config.tenant_id}.\n"
            f"Use RAG collection '{tenant_config.rag_collection}' to personalize "
            f"each message.\n"
            f"Sender: {tenant_config.sender_name} <{tenant_config.sender_email}>\n"
            f"Language: {tenant_config.language}\n"
            "After sending, update each lead's status to 'contacted'."
        ),
        agent=agents["cierre"],
        expected_output="Count of emails sent and list of outbound message IDs.",
        context=[prospect_task],
    )

    # ------------------------------------------------------------------
    # Task 3 — Follow-up & reactivation  (independent)
    # ------------------------------------------------------------------
    followup_task = Task(
        description=(
            f"Review all leads for tenant {tenant_config.tenant_id}.\n"
            f"Find leads with status='no_response' and last contact older than "
            f"{_FOLLOWUP_DAYS} days — send a follow-up sequence.\n"
            "Confirm any pending meetings and send reminders.\n"
            "Reactivate dormant leads that were previously interested."
        ),
        agent=agents["postventa"],
        expected_output=(
            "Number of reactivation attempts made and meetings confirmed."
        ),
    )

    # ------------------------------------------------------------------
    # Task 4 — Daily report  (depends on all three previous tasks)
    # ------------------------------------------------------------------
    report_task = Task(
        description=(
            f"Compile the daily sales report for {tenant_config.company_name} "
            f"(tenant: {tenant_config.tenant_id}).\n"
            "Include: leads found, emails sent, responses received, meetings booked, "
            "estimated pipeline value.\n"
            f"Write a WhatsApp summary: max 5 bullet points, plain language, "
            f"in {tenant_config.language}.\n"
            "Save the DailyReport to the database."
        ),
        agent=agents["director"],
        expected_output=(
            "DailyReport saved to database, summary_text ready for WhatsApp delivery."
        ),
        context=[prospect_task, outreach_task, followup_task],
    )

    tasks = [prospect_task, outreach_task, followup_task, report_task]

    logger.info(
        "build_daily_tasks | tenant=%s | task_count=%d",
        tenant_config.tenant_id,
        len(tasks),
    )

    return tasks
