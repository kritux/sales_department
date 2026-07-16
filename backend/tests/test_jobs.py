"""
Tests for backend/scheduler/jobs.py.

Mock strategy:
  crewai is injected into sys.modules before import so the lazy
  `from crewai import Task` inside build_daily_tasks() resolves
  to the mock without requiring the real package.

  Task.side_effect returns distinct MagicMock instances (one per call)
  so context-chaining assertions can verify *which* task objects appear
  in each context list.

Coverage:
  - Four tasks returned in correct order
  - Each task assigned to the correct agent key
  - Description content: tenant-specific strings injected correctly
  - Context chaining:
      outreach_task.context = [prospect_task]
      followup_task.context is empty (independent)
      report_task.context = [prospect, outreach, followup]
  - Expected outputs are non-empty strings
  - Different tenants produce different task descriptions
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

# ---------------------------------------------------------------------------
# Inject mock BEFORE importing jobs
# ---------------------------------------------------------------------------

_mock_crewai = MagicMock()
sys.modules.setdefault("crewai", _mock_crewai)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import TenantConfig, LeadCriteria  # noqa: E402
from scheduler.jobs import build_daily_tasks, _LEADS_TARGET, _FOLLOWUP_DAYS  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(**kwargs) -> TenantConfig:
    defaults = dict(
        tenant_id="tenant_001",
        company_name="Growth Bizon",
        language="en",
        geo_center="Houston, TX",
        geo_radius_miles=50,
        scraping_keywords=["contractor Houston", "plumber no website TX"],
        lead_criteria=LeadCriteria(
            industries=["contractor", "plumber"],
            exclude_keywords=["franchise"],
            min_rating=3.5,
            min_reviews=10,
        ),
        sender_name="Sales Team",
        sender_email="sales@growthbizon.com",
        owner_whatsapp="+15551234567",
        owner_name="Carlos",
        rag_collection="rag_tenant_001",
    )
    defaults.update(kwargs)
    return TenantConfig(**defaults)


def _make_agents() -> dict:
    return {
        "director": MagicMock(name="director_agent"),
        "prospeccion": MagicMock(name="prospeccion_agent"),
        "cierre": MagicMock(name="cierre_agent"),
        "postventa": MagicMock(name="postventa_agent"),
    }


def _task_instances():
    """Return 4 distinct MagicMock task objects for side_effect."""
    return [MagicMock(name=f"task_{i}") for i in range(4)]


@pytest.fixture(autouse=True)
def reset_crewai():
    _mock_crewai.reset_mock(side_effect=True)
    yield


# ---------------------------------------------------------------------------
# Return value structure
# ---------------------------------------------------------------------------

class TestReturnStructure:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.agents = _make_agents()
        tasks = _task_instances()
        _mock_crewai.Task.side_effect = tasks
        self.result = build_daily_tasks(self.tenant, self.agents)

    def test_returns_list(self):
        assert isinstance(self.result, list)

    def test_returns_four_tasks(self):
        assert len(self.result) == 4

    def test_task_class_called_four_times(self):
        assert _mock_crewai.Task.call_count == 4

    def test_tasks_in_order_prospect_outreach_followup_report(self):
        calls = _mock_crewai.Task.call_args_list
        roles = [c[1].get("agent") for c in calls]
        assert roles[0] is self.agents["prospeccion"]
        assert roles[1] is self.agents["cierre"]
        assert roles[2] is self.agents["postventa"]
        assert roles[3] is self.agents["director"]


# ---------------------------------------------------------------------------
# Agent assignment
# ---------------------------------------------------------------------------

class TestAgentAssignment:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.agents = _make_agents()
        _mock_crewai.Task.side_effect = _task_instances()
        build_daily_tasks(self.tenant, self.agents)
        self.calls = _mock_crewai.Task.call_args_list

    def test_prospect_task_assigned_to_prospeccion(self):
        _, kwargs = self.calls[0]
        assert kwargs["agent"] is self.agents["prospeccion"]

    def test_outreach_task_assigned_to_cierre(self):
        _, kwargs = self.calls[1]
        assert kwargs["agent"] is self.agents["cierre"]

    def test_followup_task_assigned_to_postventa(self):
        _, kwargs = self.calls[2]
        assert kwargs["agent"] is self.agents["postventa"]

    def test_report_task_assigned_to_director(self):
        _, kwargs = self.calls[3]
        assert kwargs["agent"] is self.agents["director"]


# ---------------------------------------------------------------------------
# Context chaining
# ---------------------------------------------------------------------------

class TestContextChaining:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.agents = _make_agents()
        self.task_mocks = _task_instances()
        _mock_crewai.Task.side_effect = list(self.task_mocks)
        build_daily_tasks(self.tenant, self.agents)
        self.calls = _mock_crewai.Task.call_args_list

    def test_prospect_task_has_no_context(self):
        _, kwargs = self.calls[0]
        assert kwargs.get("context") is None or kwargs.get("context") == []

    def test_outreach_context_contains_prospect(self):
        _, kwargs = self.calls[1]
        assert self.task_mocks[0] in kwargs["context"]

    def test_outreach_context_length_is_one(self):
        _, kwargs = self.calls[1]
        assert len(kwargs["context"]) == 1

    def test_followup_task_has_no_context(self):
        _, kwargs = self.calls[2]
        assert kwargs.get("context") is None or kwargs.get("context") == []

    def test_report_context_contains_prospect(self):
        _, kwargs = self.calls[3]
        assert self.task_mocks[0] in kwargs["context"]

    def test_report_context_contains_outreach(self):
        _, kwargs = self.calls[3]
        assert self.task_mocks[1] in kwargs["context"]

    def test_report_context_contains_followup(self):
        _, kwargs = self.calls[3]
        assert self.task_mocks[2] in kwargs["context"]

    def test_report_context_length_is_three(self):
        _, kwargs = self.calls[3]
        assert len(kwargs["context"]) == 3


# ---------------------------------------------------------------------------
# Prospect task description content
# ---------------------------------------------------------------------------

class TestProspectTaskDescription:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.agents = _make_agents()
        _mock_crewai.Task.side_effect = _task_instances()
        build_daily_tasks(self.tenant, self.agents)
        _, self.kwargs = _mock_crewai.Task.call_args_list[0]

    def test_description_mentions_company_name(self):
        assert "Growth Bizon" in self.kwargs["description"]

    def test_description_mentions_geo_center(self):
        assert "Houston" in self.kwargs["description"]

    def test_description_mentions_radius(self):
        assert "50" in self.kwargs["description"]

    def test_description_mentions_scraping_keywords(self):
        assert "contractor Houston" in self.kwargs["description"]

    def test_description_mentions_leads_target(self):
        assert str(_LEADS_TARGET) in self.kwargs["description"]

    def test_expected_output_is_nonempty(self):
        assert len(self.kwargs["expected_output"]) > 5


# ---------------------------------------------------------------------------
# Outreach task description content
# ---------------------------------------------------------------------------

class TestOutreachTaskDescription:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.agents = _make_agents()
        _mock_crewai.Task.side_effect = _task_instances()
        build_daily_tasks(self.tenant, self.agents)
        _, self.kwargs = _mock_crewai.Task.call_args_list[1]

    def test_description_mentions_tenant_id(self):
        assert "tenant_001" in self.kwargs["description"]

    def test_description_mentions_rag_collection(self):
        assert "rag_tenant_001" in self.kwargs["description"]

    def test_description_mentions_sender_name(self):
        assert "Sales Team" in self.kwargs["description"]

    def test_description_mentions_sender_email(self):
        assert "sales@growthbizon.com" in self.kwargs["description"]

    def test_description_mentions_language(self):
        assert "en" in self.kwargs["description"]

    def test_expected_output_is_nonempty(self):
        assert len(self.kwargs["expected_output"]) > 5


# ---------------------------------------------------------------------------
# Follow-up task description content
# ---------------------------------------------------------------------------

class TestFollowupTaskDescription:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.agents = _make_agents()
        _mock_crewai.Task.side_effect = _task_instances()
        build_daily_tasks(self.tenant, self.agents)
        _, self.kwargs = _mock_crewai.Task.call_args_list[2]

    def test_description_mentions_tenant_id(self):
        assert "tenant_001" in self.kwargs["description"]

    def test_description_mentions_followup_days(self):
        assert str(_FOLLOWUP_DAYS) in self.kwargs["description"]

    def test_description_mentions_no_response(self):
        assert "no_response" in self.kwargs["description"]

    def test_expected_output_is_nonempty(self):
        assert len(self.kwargs["expected_output"]) > 5


# ---------------------------------------------------------------------------
# Report task description content
# ---------------------------------------------------------------------------

class TestReportTaskDescription:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.agents = _make_agents()
        _mock_crewai.Task.side_effect = _task_instances()
        build_daily_tasks(self.tenant, self.agents)
        _, self.kwargs = _mock_crewai.Task.call_args_list[3]

    def test_description_mentions_company_name(self):
        assert "Growth Bizon" in self.kwargs["description"]

    def test_description_mentions_tenant_id(self):
        assert "tenant_001" in self.kwargs["description"]

    def test_description_mentions_language(self):
        assert "en" in self.kwargs["description"]

    def test_description_mentions_whatsapp(self):
        assert "WhatsApp" in self.kwargs["description"]

    def test_expected_output_is_nonempty(self):
        assert len(self.kwargs["expected_output"]) > 5


# ---------------------------------------------------------------------------
# Different tenant produces different descriptions
# ---------------------------------------------------------------------------

class TestMultiTenant:
    def test_different_company_name_in_prospect_task(self):
        tenant_b = _make_tenant(
            tenant_id="tenant_002",
            company_name="Soldadura Corp",
            geo_center="Dallas, TX",
        )
        agents = _make_agents()

        _mock_crewai.reset_mock(side_effect=True)
        _mock_crewai.Task.side_effect = _task_instances()
        build_daily_tasks(tenant_b, agents)

        _, kwargs = _mock_crewai.Task.call_args_list[0]
        assert "Soldadura Corp" in kwargs["description"]
        assert "Growth Bizon" not in kwargs["description"]

    def test_different_tenant_id_in_outreach_task(self):
        tenant_b = _make_tenant(tenant_id="tenant_002", company_name="CorpB")
        agents = _make_agents()

        _mock_crewai.reset_mock(side_effect=True)
        _mock_crewai.Task.side_effect = _task_instances()
        build_daily_tasks(tenant_b, agents)

        _, kwargs = _mock_crewai.Task.call_args_list[1]
        assert "tenant_002" in kwargs["description"]
