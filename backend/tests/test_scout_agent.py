"""
Tests for backend/agents/prospeccion/scout.py.

All external packages (crewai, langchain, langchain_anthropic) are mocked via
sys.modules injection before import. This keeps the suite hermetic — no AI
packages need to be installed.

Mock strategy for @tool("name"):
  langchain.tools.tool is replaced with an identity decorator factory so
  @tool("scrape_leads") def fn(...) → fn is returned unchanged.
  This lets tests call the tool functions as plain Python functions.

Coverage:
  - _make_scrape_tool: calls scrape_google_maps, returns JSON, captures tenant
  - _make_qualify_tool: calls filter_leads, handles invalid input, returns JSON
  - build_scout_agent: creates Agent with correct role/goal/tools/llm
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Inject mocks BEFORE importing scout module
# ---------------------------------------------------------------------------

# langchain.tools.tool mock — acts as identity decorator so inner functions
# remain plain callables in tests.
def _tool_identity(name_or_fn):
    """Mimic @tool("name") and @tool usage as an identity pass-through."""
    if callable(name_or_fn):
        return name_or_fn  # @tool without arguments
    return lambda fn: fn   # @tool("name") — returns decorator that returns fn unchanged

_mock_langchain_tools = MagicMock()
_mock_langchain_tools.tool = _tool_identity

_mock_langchain = MagicMock()
_mock_langchain.tools = _mock_langchain_tools

sys.modules.setdefault("langchain", _mock_langchain)
sys.modules.setdefault("langchain.tools", _mock_langchain_tools)

# crewai.Agent mock
_mock_crewai = MagicMock()
sys.modules.setdefault("crewai", _mock_crewai)

# langchain_anthropic mock
_mock_langchain_anthropic = MagicMock()
sys.modules.setdefault("langchain_anthropic", _mock_langchain_anthropic)

# Now safe to import our module
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import TenantConfig, LeadCriteria
from db.models import Lead
from agents.prospeccion.scout import (
    _make_scrape_tool,
    _make_qualify_tool,
    build_scout_agent,
    _LEADS_PER_KEYWORD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime.utcnow().isoformat()


def _make_tenant(**kwargs) -> TenantConfig:
    defaults = dict(
        tenant_id="tenant_001",
        company_name="Growth Bizon",
        language="en",
        geo_center="Houston, TX",
        scraping_keywords=["contractor no website Houston", "plumber no website TX"],
        lead_criteria=LeadCriteria(
            industries=["contractor", "plumber"],
            exclude_keywords=["chain", "franchise"],
        ),
        sender_name="Sales Team",
        sender_email="sales@growthbizon.com",
        owner_whatsapp="+15551234567",
        owner_name="Carlos",
        rag_collection="rag_tenant_001",
    )
    defaults.update(kwargs)
    return TenantConfig(**defaults)


def _raw_lead(**kwargs) -> dict:
    base = dict(
        tenant_id="tenant_001",
        company_name="Acme Contracting",
        address="123 Main St, Houston, TX 77001",
        city="Houston",
        state="TX",
        phone="+17135550001",
        email=None,
        website=None,
        rating=4.5,
        review_count=100,
        category="General Contractor",
        score=0,
        source="google_maps",
        status="new",
        last_contact_at=None,
        notes="",
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(kwargs)
    return base


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_crewai.reset_mock(side_effect=True)
    _mock_langchain_anthropic.reset_mock(side_effect=True)
    # Re-inject so test_director.py (which also injects crewai/langchain_anthropic)
    # doesn't leave a different mock in sys.modules when the suite runs together.
    sys.modules["crewai"] = _mock_crewai
    sys.modules["langchain_anthropic"] = _mock_langchain_anthropic
    yield


# ---------------------------------------------------------------------------
# _make_scrape_tool
# ---------------------------------------------------------------------------

class TestMakeScrapeToolCallsBackend:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.tool = _make_scrape_tool(self.tenant)

    def test_tool_is_callable(self):
        assert callable(self.tool)

    def test_calls_scrape_google_maps(self):
        with patch("agents.prospeccion.scout.scrape_google_maps", return_value=[]) as mock_scrape:
            self.tool("contractor Houston")
        mock_scrape.assert_called_once()

    def test_passes_query_stripped(self):
        with patch("agents.prospeccion.scout.scrape_google_maps", return_value=[]) as mock_scrape:
            self.tool("  contractor Houston  ")
        args, kwargs = mock_scrape.call_args
        assert kwargs.get("query", args[0] if args else None) == "contractor Houston"

    def test_passes_tenant_id_from_closure(self):
        with patch("agents.prospeccion.scout.scrape_google_maps", return_value=[]) as mock_scrape:
            self.tool("query")
        _, kwargs = mock_scrape.call_args
        assert kwargs.get("tenant_id") == "tenant_001"

    def test_passes_limit(self):
        with patch("agents.prospeccion.scout.scrape_google_maps", return_value=[]) as mock_scrape:
            self.tool("query")
        _, kwargs = mock_scrape.call_args
        assert kwargs.get("limit") == _LEADS_PER_KEYWORD

    def test_returns_json_string(self):
        raw = [_raw_lead()]
        with patch("agents.prospeccion.scout.scrape_google_maps", return_value=raw):
            result = self.tool("query")
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_returns_all_raw_leads(self):
        raw = [_raw_lead(), _raw_lead(company_name="Beta Corp")]
        with patch("agents.prospeccion.scout.scrape_google_maps", return_value=raw):
            result = self.tool("query")
        parsed = json.loads(result)
        assert len(parsed) == 2

    def test_empty_result_returns_empty_json_list(self):
        with patch("agents.prospeccion.scout.scrape_google_maps", return_value=[]):
            result = self.tool("query")
        assert json.loads(result) == []

    def test_different_tenants_use_different_tenant_ids(self):
        tenant_b = _make_tenant(tenant_id="tenant_002")
        tool_b = _make_scrape_tool(tenant_b)

        with patch("agents.prospeccion.scout.scrape_google_maps", return_value=[]) as mock_b:
            tool_b("query")
        _, kwargs_b = mock_b.call_args
        assert kwargs_b.get("tenant_id") == "tenant_002"


# ---------------------------------------------------------------------------
# _make_qualify_tool
# ---------------------------------------------------------------------------

class TestMakeQualifyToolCallsBackend:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.tool = _make_qualify_tool(self.tenant)

    def _qualified_lead(self, **kwargs) -> Lead:
        defaults = dict(
            id="uuid-001",
            tenant_id="tenant_001",
            company_name="Acme",
            address="123 Main",
            city="Houston",
            state="TX",
            phone=None,
            email=None,
            website=None,
            rating=4.5,
            review_count=100,
            category="General Contractor",
            score=85,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        defaults.update(kwargs)
        return Lead(**defaults)

    def test_tool_is_callable(self):
        assert callable(self.tool)

    def test_calls_filter_leads(self):
        raw = [_raw_lead()]
        with patch("agents.prospeccion.scout.filter_leads", return_value=[]) as mock_filter:
            self.tool(json.dumps(raw))
        mock_filter.assert_called_once()

    def test_passes_raw_leads_to_filter(self):
        raw = [_raw_lead()]
        with patch("agents.prospeccion.scout.filter_leads", return_value=[]) as mock_filter:
            self.tool(json.dumps(raw))
        args, kwargs = mock_filter.call_args
        passed_raw = kwargs.get("raw_leads", args[0] if args else None)
        assert len(passed_raw) == 1
        assert passed_raw[0]["company_name"] == "Acme Contracting"

    def test_passes_criteria_from_closure(self):
        with patch("agents.prospeccion.scout.filter_leads", return_value=[]) as mock_filter:
            self.tool(json.dumps([_raw_lead()]))
        args, kwargs = mock_filter.call_args
        criteria = kwargs.get("criteria", args[1] if len(args) > 1 else None)
        assert criteria == self.tenant.lead_criteria

    def test_passes_tenant_id_from_closure(self):
        with patch("agents.prospeccion.scout.filter_leads", return_value=[]) as mock_filter:
            self.tool(json.dumps([_raw_lead()]))
        args, kwargs = mock_filter.call_args
        tid = kwargs.get("tenant_id", args[2] if len(args) > 2 else None)
        assert tid == "tenant_001"

    def test_returns_json_string(self):
        lead = self._qualified_lead()
        with patch("agents.prospeccion.scout.filter_leads", return_value=[lead]):
            result = self.tool(json.dumps([_raw_lead()]))
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_returns_qualified_leads_data(self):
        lead = self._qualified_lead(score=85)
        with patch("agents.prospeccion.scout.filter_leads", return_value=[lead]):
            result = self.tool(json.dumps([_raw_lead()]))
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["score"] == 85

    def test_empty_qualified_list_returns_empty_json(self):
        with patch("agents.prospeccion.scout.filter_leads", return_value=[]):
            result = self.tool(json.dumps([_raw_lead()]))
        assert json.loads(result) == []


class TestMakeQualifyToolInvalidInput:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.tool = _make_qualify_tool(self.tenant)

    def test_invalid_json_returns_error_dict(self):
        result = self.tool("not valid json {{{")
        parsed = json.loads(result)
        assert parsed["error"] == "invalid_json"
        assert parsed["qualified_count"] == 0

    def test_invalid_json_leads_list_is_empty(self):
        result = self.tool("not valid json")
        parsed = json.loads(result)
        assert parsed["leads"] == []

    def test_non_list_json_returns_error_dict(self):
        result = self.tool(json.dumps({"key": "value"}))
        parsed = json.loads(result)
        assert parsed["error"] == "expected_list"

    def test_non_list_qualified_count_is_zero(self):
        result = self.tool(json.dumps("a string"))
        parsed = json.loads(result)
        assert parsed["qualified_count"] == 0

    def test_invalid_input_never_calls_filter_leads(self):
        with patch("agents.prospeccion.scout.filter_leads") as mock_filter:
            self.tool("not json")
        mock_filter.assert_not_called()

    def test_empty_list_calls_filter_leads(self):
        with patch("agents.prospeccion.scout.filter_leads", return_value=[]) as mock_filter:
            self.tool(json.dumps([]))
        mock_filter.assert_called_once()

    def test_null_json_returns_error_dict(self):
        result = self.tool("null")
        parsed = json.loads(result)
        assert "error" in parsed


# ---------------------------------------------------------------------------
# build_scout_agent
# ---------------------------------------------------------------------------

class TestBuildScoutAgent:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_returns_agent_instance(self):
        result = build_scout_agent(self.tenant)
        _mock_crewai.Agent.assert_called_once()
        assert result is _mock_crewai.Agent.return_value

    def test_agent_role_is_lead_scout(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert kwargs["role"] == "Lead Scout"

    def test_goal_mentions_company_name(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "Growth Bizon" in kwargs["goal"]

    def test_goal_mentions_each_keyword(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "contractor no website Houston" in kwargs["goal"]
        assert "plumber no website TX" in kwargs["goal"]

    def test_goal_mentions_target_industries(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "contractor" in kwargs["goal"] or "plumber" in kwargs["goal"]

    def test_agent_has_two_tools(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert len(kwargs["tools"]) == 2

    def test_tools_are_callable(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        for t in kwargs["tools"]:
            assert callable(t)

    def test_allow_delegation_is_false(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert kwargs["allow_delegation"] is False

    def test_verbose_is_true(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert kwargs["verbose"] is True

    def test_llm_is_set(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "llm" in kwargs
        assert kwargs["llm"] is not None

    def test_haiku_model_used(self):
        build_scout_agent(self.tenant)
        call_args = _mock_langchain_anthropic.ChatAnthropic.call_args
        assert call_args is not None
        model_arg = (
            call_args[1].get("model")
            or (call_args[0][0] if call_args[0] else None)
        )
        assert "haiku" in str(model_arg)

    def test_different_tenant_gets_different_goal(self):
        tenant_b = _make_tenant(
            tenant_id="tenant_002",
            company_name="Soldadura Corp",
            scraping_keywords=["welder Houston"],
        )
        _mock_crewai.reset_mock()
        build_scout_agent(tenant_b)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "Soldadura Corp" in kwargs["goal"]
        assert "welder Houston" in kwargs["goal"]

    def test_backstory_is_set(self):
        build_scout_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "backstory" in kwargs
        assert len(kwargs["backstory"]) > 10

    def test_no_keywords_goal_still_builds(self):
        tenant_empty = _make_tenant(scraping_keywords=[])
        build_scout_agent(tenant_empty)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "Growth Bizon" in kwargs["goal"]
