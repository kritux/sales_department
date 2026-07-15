"""
CrewAI Scout agent — scrape and qualify leads for a tenant.

Role in the system (TEAM.md):
  Sub-agent under Prospection Manager. Driven by CrewAI Tasks; writes nothing
  to the database itself — the Manager persists qualified leads.

LangChain tools (both use closures to capture tenant_config):
  scrape_leads(query)        — calls maps_scraper.scrape_google_maps()
                               returns JSON list of raw lead dicts
  qualify_leads(raw_json)    — calls lead_filter.filter_leads()
                               returns JSON list of qualified Lead objects

Usage:
    from config.tenants import TenantConfig
    from agents.prospeccion.scout import build_scout_agent

    agent = build_scout_agent(tenant_config)
    # Pass to a CrewAI Crew/Task — agent owns the tools, CrewAI drives execution.

All external package imports (crewai, langchain, langchain_anthropic) are lazy
so this module loads cleanly in dry-run / test contexts.
"""

import json
import logging
from typing import TYPE_CHECKING, List

from config.tenants import TenantConfig
from tools.lead_filter import SCORE_FLOOR, filter_leads
from tools.maps_scraper import MAX_LEADS_PER_SESSION, scrape_google_maps

if TYPE_CHECKING:
    from crewai import Agent  # type: ignore

logger = logging.getLogger(__name__)

# Leads to fetch per keyword. Keeps each search focused; the per-session cap
# of MAX_LEADS_PER_SESSION is enforced inside maps_scraper itself.
_LEADS_PER_KEYWORD = 20


# ---------------------------------------------------------------------------
# Tool factories — closures capture tenant_config at build time
# ---------------------------------------------------------------------------

def _make_scrape_tool(tenant_config: TenantConfig):
    """Return a LangChain tool that scrapes Google Maps for this tenant."""
    from langchain.tools import tool  # lazy — requires langchain at runtime

    @tool("scrape_leads")
    def scrape_leads(query: str) -> str:
        """
        Search Google Maps for businesses matching the given query.

        Returns a JSON list of raw lead dicts (unscored). Pass the result
        directly to qualify_leads() to score and filter them.

        Args:
            query: Full search string, e.g. "contractor no website Houston TX"
        """
        logger.info(
            "scrape_leads | tenant=%s | query=%r",
            tenant_config.tenant_id, query,
        )
        raw = scrape_google_maps(
            query=query.strip(),
            limit=_LEADS_PER_KEYWORD,
            tenant_id=tenant_config.tenant_id,
        )
        logger.info(
            "scrape_leads | tenant=%s | raw_count=%d",
            tenant_config.tenant_id, len(raw),
        )
        return json.dumps(raw, default=str)

    return scrape_leads


def _make_qualify_tool(tenant_config: TenantConfig):
    """Return a LangChain tool that filters and scores leads for this tenant."""
    from langchain.tools import tool  # lazy

    @tool("qualify_leads")
    def qualify_leads(raw_leads_json: str) -> str:
        """
        Score and filter raw leads returned by scrape_leads().

        Applies the tenant's LeadCriteria: scoring rules, exclude keywords,
        and the score floor (> 30). Returns leads sorted by score DESC.

        Args:
            raw_leads_json: JSON string (list) returned by scrape_leads()
        """
        try:
            raw: List = json.loads(raw_leads_json)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("qualify_leads: invalid JSON input — %s", exc)
            return json.dumps({
                "error": "invalid_json",
                "qualified_count": 0,
                "leads": [],
            })

        if not isinstance(raw, list):
            logger.warning("qualify_leads: expected list, got %s", type(raw).__name__)
            return json.dumps({
                "error": "expected_list",
                "qualified_count": 0,
                "leads": [],
            })

        qualified = filter_leads(
            raw_leads=raw,
            criteria=tenant_config.lead_criteria,
            tenant_id=tenant_config.tenant_id,
        )
        logger.info(
            "qualify_leads | tenant=%s | raw=%d | qualified=%d (score > %d)",
            tenant_config.tenant_id, len(raw), len(qualified), SCORE_FLOOR,
        )
        return json.dumps(
            [lead.model_dump(mode="json") for lead in qualified],
            default=str,
        )

    return qualify_leads


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def build_scout_agent(tenant_config: TenantConfig) -> "Agent":
    """
    Build and return a CrewAI Scout Agent configured for this tenant.

    The agent carries two tools (scrape_leads, qualify_leads) and is
    designed to run as a sub-agent under the Prospection Manager.

    The expected task execution loop:
      for keyword in tenant_config.scraping_keywords:
          raw_json   = scrape_leads(keyword)
          qualified  = qualify_leads(raw_json)
          # collect results — Manager persists to Supabase

    Args:
        tenant_config: Fully populated TenantConfig for this tenant.

    Returns:
        CrewAI Agent instance ready to be assigned Tasks.
    """
    from crewai import Agent  # lazy
    from langchain_anthropic import ChatAnthropic  # lazy

    scrape_tool = _make_scrape_tool(tenant_config)
    qualify_tool = _make_qualify_tool(tenant_config)

    keywords_str = ", ".join(f'"{kw}"' for kw in tenant_config.scraping_keywords)
    criteria = tenant_config.lead_criteria

    return Agent(
        role="Lead Scout",
        goal=(
            f"Find and qualify leads for {tenant_config.company_name}. "
            f"Search Google Maps using these keywords: {keywords_str}. "
            f"For each keyword: call scrape_leads, then call qualify_leads on "
            f"the result. Target industries: {criteria.industries or ['any']}. "
            f"Exclude: {criteria.exclude_keywords or ['none']}."
        ),
        backstory=(
            "You are a lead prospection specialist with deep knowledge of "
            "Google Maps business data. You systematically search for "
            "businesses that match your client's target profile, then filter "
            "for the highest-quality prospects based on ratings, review count, "
            "industry match, and whether they already have a website."
        ),
        llm=ChatAnthropic(model="claude-haiku-20240307"),
        tools=[scrape_tool, qualify_tool],
        verbose=True,
        allow_delegation=False,
    )
