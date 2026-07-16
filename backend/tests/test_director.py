"""
Tests for backend/agents/director.py.

Mock strategy:
  - crewai, langchain_anthropic: injected into sys.modules before import
    (lazy-loaded inside _build_agents / _build_crew)
  - scheduler.jobs: replaced in sys.modules so the late import inside
    run_daily() resolves to the mock without touching the real module
  - send_whatsapp_summary, is_whatsapp_read, alert_owner_by_voice:
    patched on the agents.director namespace in each test

Coverage:
  - _build_agents: four agents, correct roles, LLM models, delegation flags
  - _build_crew: Process.hierarchical, manager_agent=director
  - build_director_crew: wires agents + tasks correctly
  - end_of_day_sequence: WA delivery, voice escalation, read-receipt branch
  - run_daily: full pipeline — agents → tasks → crew → kickoff → EoD
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inject mocks BEFORE importing director
# ---------------------------------------------------------------------------

_mock_crewai = MagicMock()
_mock_langchain_anthropic = MagicMock()
_mock_jobs = MagicMock()
_mock_jobs.build_daily_tasks.return_value = []

sys.modules.setdefault("crewai", _mock_crewai)
sys.modules.setdefault("langchain_anthropic", _mock_langchain_anthropic)
sys.modules["scheduler"] = MagicMock()
sys.modules["scheduler.jobs"] = _mock_jobs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import TenantConfig, LeadCriteria  # noqa: E402
from agents.director import (  # noqa: E402
    _build_agents,
    _build_crew,
    build_director_crew,
    end_of_day_sequence,
    run_daily,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(**kwargs) -> TenantConfig:
    defaults = dict(
        tenant_id="tenant_001",
        company_name="Growth Bizon",
        language="en",
        geo_center="Houston, TX",
        scraping_keywords=["contractor Houston"],
        lead_criteria=LeadCriteria(
            industries=["contractor"],
            exclude_keywords=["franchise"],
        ),
        sender_name="Sales Team",
        sender_email="sales@growthbizon.com",
        owner_whatsapp="+15551234567",
        owner_name="Carlos",
        rag_collection="rag_tenant_001",
    )
    defaults.update(kwargs)
    return TenantConfig(**defaults)


def _make_wa_msg(status="sent", message_id="SMXXX"):
    from tools.email_tool import OutboundMessage  # noqa: PLC0415
    return OutboundMessage(
        tenant_id="tenant_001",
        lead_id="director",
        channel="whatsapp",
        recipient="+15551234567",
        subject=None,
        body="summary",
        sent_at=None,
        status=status,
        dry_run=False,
        message_id=message_id,
    )


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_crewai.reset_mock(side_effect=True)
    _mock_langchain_anthropic.reset_mock(side_effect=True)
    _mock_jobs.reset_mock(side_effect=True)
    _mock_jobs.build_daily_tasks.return_value = []
    yield


# ---------------------------------------------------------------------------
# _build_agents
# ---------------------------------------------------------------------------

class TestBuildAgents:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.agents = _build_agents(self.tenant)

    def test_returns_four_keys(self):
        assert set(self.agents.keys()) == {"director", "prospeccion", "cierre", "postventa"}

    def test_agent_call_count_is_four(self):
        assert _mock_crewai.Agent.call_count == 4

    def test_director_role(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[0]
        assert kwargs["role"] == "Sales Director"

    def test_director_allow_delegation_true(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[0]
        assert kwargs["allow_delegation"] is True

    def test_director_verbose_true(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[0]
        assert kwargs["verbose"] is True

    def test_director_has_llm(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[0]
        assert kwargs.get("llm") is not None

    def test_director_goal_mentions_company_name(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[0]
        assert "Growth Bizon" in kwargs["goal"]

    def test_director_goal_mentions_tenant_id(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[0]
        assert "tenant_001" in kwargs["goal"]

    def test_director_has_backstory(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[0]
        assert len(kwargs.get("backstory", "")) > 10

    def test_prospeccion_role(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[1]
        assert kwargs["role"] == "Prospection Manager"

    def test_prospeccion_allow_delegation_true(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[1]
        assert kwargs["allow_delegation"] is True

    def test_prospeccion_goal_mentions_geo_center(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[1]
        assert "Houston" in kwargs["goal"]

    def test_cierre_role(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[2]
        assert kwargs["role"] == "Sales Closer Manager"

    def test_cierre_allow_delegation_true(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[2]
        assert kwargs["allow_delegation"] is True

    def test_cierre_goal_mentions_sender_email(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[2]
        assert "sales@growthbizon.com" in kwargs["goal"]

    def test_cierre_goal_mentions_language(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[2]
        assert "en" in kwargs["goal"]

    def test_postventa_role(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[3]
        assert kwargs["role"] == "Post-Sale Manager"

    def test_postventa_allow_delegation_true(self):
        _, kwargs = _mock_crewai.Agent.call_args_list[3]
        assert kwargs["allow_delegation"] is True

    def test_all_agents_have_backstory(self):
        for c in _mock_crewai.Agent.call_args_list:
            _, kwargs = c
            assert len(kwargs.get("backstory", "")) > 10

    def test_haiku_model_used(self):
        calls = _mock_langchain_anthropic.ChatAnthropic.call_args_list
        model_args = [
            c[1].get("model") or (c[0][0] if c[0] else "") for c in calls
        ]
        assert any("haiku" in str(m) for m in model_args)

    def test_sonnet_model_used(self):
        calls = _mock_langchain_anthropic.ChatAnthropic.call_args_list
        model_args = [
            c[1].get("model") or (c[0][0] if c[0] else "") for c in calls
        ]
        assert any("sonnet" in str(m) for m in model_args)

    def test_two_llm_instances_created(self):
        assert _mock_langchain_anthropic.ChatAnthropic.call_count == 2

    def test_different_tenant_gets_different_goal(self):
        tenant_b = _make_tenant(tenant_id="tenant_002", company_name="Soldadura Corp")
        _mock_crewai.reset_mock(side_effect=True)
        _mock_langchain_anthropic.reset_mock(side_effect=True)
        agents_b = _build_agents(tenant_b)
        _, kwargs = _mock_crewai.Agent.call_args_list[0]
        assert "Soldadura Corp" in kwargs["goal"]


# ---------------------------------------------------------------------------
# _build_crew
# ---------------------------------------------------------------------------

class TestBuildCrew:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.agents = _build_agents(self.tenant)
        _mock_crewai.reset_mock(side_effect=True)

    def test_crew_called_once(self):
        _build_crew(self.agents, [])
        _mock_crewai.Crew.assert_called_once()

    def test_crew_uses_hierarchical_process(self):
        _build_crew(self.agents, [])
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["process"] == _mock_crewai.Process.hierarchical

    def test_manager_agent_is_director(self):
        _build_crew(self.agents, [])
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["manager_agent"] is self.agents["director"]

    def test_agents_list_has_four_entries(self):
        _build_crew(self.agents, [])
        _, kwargs = _mock_crewai.Crew.call_args
        assert len(kwargs["agents"]) == 4

    def test_tasks_passed_through(self):
        fake_tasks = [MagicMock(), MagicMock()]
        _build_crew(self.agents, fake_tasks)
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["tasks"] == fake_tasks

    def test_empty_tasks_accepted(self):
        _build_crew(self.agents, [])
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["tasks"] == []

    def test_verbose_true(self):
        _build_crew(self.agents, [])
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["verbose"] is True

    def test_returns_crew_instance(self):
        result = _build_crew(self.agents, [])
        assert result is _mock_crewai.Crew.return_value


# ---------------------------------------------------------------------------
# build_director_crew
# ---------------------------------------------------------------------------

class TestBuildDirectorCrew:
    def setup_method(self):
        self.tenant = _make_tenant()
        _mock_crewai.reset_mock(side_effect=True)
        _mock_langchain_anthropic.reset_mock(side_effect=True)

    def test_returns_crew(self):
        result = build_director_crew(self.tenant)
        assert result is _mock_crewai.Crew.return_value

    def test_builds_four_agents(self):
        build_director_crew(self.tenant)
        assert _mock_crewai.Agent.call_count == 4

    def test_accepts_task_list(self):
        fake_tasks = [MagicMock()]
        build_director_crew(self.tenant, tasks=fake_tasks)
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["tasks"] == fake_tasks

    def test_tasks_defaults_to_empty_list(self):
        build_director_crew(self.tenant)
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["tasks"] == []

    def test_none_tasks_uses_empty_list(self):
        build_director_crew(self.tenant, tasks=None)
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["tasks"] == []

    def test_hierarchical_process_set(self):
        build_director_crew(self.tenant)
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["process"] == _mock_crewai.Process.hierarchical


# ---------------------------------------------------------------------------
# end_of_day_sequence
# ---------------------------------------------------------------------------

class TestEndOfDaySequence:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_sends_whatsapp_with_summary(self):
        wa_msg = _make_wa_msg(status="sent", message_id="SMXXX")
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg) as mock_wa, \
             patch("agents.director.is_whatsapp_read", return_value=True), \
             patch("agents.director.alert_owner_by_voice"):
            end_of_day_sequence(self.tenant, "daily summary", _wa_wait_seconds=0)
        mock_wa.assert_called_once()
        args, kwargs = mock_wa.call_args
        assert args[0] is self.tenant
        assert args[1] == "daily summary"

    def test_dry_run_forwarded_to_whatsapp(self):
        wa_msg = _make_wa_msg(status="sent", message_id="SMXXX")
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg) as mock_wa, \
             patch("agents.director.is_whatsapp_read", return_value=True), \
             patch("agents.director.alert_owner_by_voice"):
            end_of_day_sequence(self.tenant, "s", dry_run=True, _wa_wait_seconds=0)
        _, kwargs = mock_wa.call_args
        assert kwargs["dry_run"] is True

    def test_voice_escalated_when_unread(self):
        wa_msg = _make_wa_msg(status="sent", message_id="SMXXX")
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read", return_value=False), \
             patch("agents.director.alert_owner_by_voice") as mock_voice:
            end_of_day_sequence(self.tenant, "summary", _wa_wait_seconds=0)
        mock_voice.assert_called_once()

    def test_no_voice_when_read(self):
        wa_msg = _make_wa_msg(status="sent", message_id="SMXXX")
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read", return_value=True), \
             patch("agents.director.alert_owner_by_voice") as mock_voice:
            end_of_day_sequence(self.tenant, "summary", _wa_wait_seconds=0)
        mock_voice.assert_not_called()

    def test_no_voice_when_wa_failed(self):
        wa_msg = _make_wa_msg(status="failed", message_id=None)
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read") as mock_read, \
             patch("agents.director.alert_owner_by_voice") as mock_voice:
            end_of_day_sequence(self.tenant, "summary", _wa_wait_seconds=0)
        mock_voice.assert_not_called()
        mock_read.assert_not_called()

    def test_no_voice_when_wa_dry_run(self):
        wa_msg = _make_wa_msg(status="dry_run", message_id=None)
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read") as mock_read, \
             patch("agents.director.alert_owner_by_voice") as mock_voice:
            end_of_day_sequence(self.tenant, "summary", _wa_wait_seconds=0)
        mock_voice.assert_not_called()
        mock_read.assert_not_called()

    def test_no_voice_when_message_id_missing(self):
        wa_msg = _make_wa_msg(status="sent", message_id=None)
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read") as mock_read, \
             patch("agents.director.alert_owner_by_voice") as mock_voice:
            end_of_day_sequence(self.tenant, "summary", _wa_wait_seconds=0)
        mock_voice.assert_not_called()

    def test_read_receipt_checked_with_correct_message_id(self):
        wa_msg = _make_wa_msg(status="sent", message_id="SM_SPECIFIC")
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read", return_value=True) as mock_read, \
             patch("agents.director.alert_owner_by_voice"):
            end_of_day_sequence(self.tenant, "summary", _wa_wait_seconds=0)
        mock_read.assert_called_once_with("SM_SPECIFIC", dry_run=None)

    def test_read_receipt_dry_run_forwarded(self):
        wa_msg = _make_wa_msg(status="sent", message_id="SMXXX")
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read", return_value=True) as mock_read, \
             patch("agents.director.alert_owner_by_voice"):
            end_of_day_sequence(self.tenant, "s", dry_run=True, _wa_wait_seconds=0)
        _, kwargs = mock_read.call_args
        assert kwargs["dry_run"] is True

    def test_voice_receives_tenant_config(self):
        wa_msg = _make_wa_msg(status="sent", message_id="SMXXX")
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read", return_value=False), \
             patch("agents.director.alert_owner_by_voice") as mock_voice:
            end_of_day_sequence(self.tenant, "update", _wa_wait_seconds=0)
        args, _ = mock_voice.call_args
        assert args[0] is self.tenant

    def test_voice_message_contains_summary(self):
        wa_msg = _make_wa_msg(status="sent", message_id="SMXXX")
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read", return_value=False), \
             patch("agents.director.alert_owner_by_voice") as mock_voice:
            end_of_day_sequence(self.tenant, "critical update", _wa_wait_seconds=0)
        args, _ = mock_voice.call_args
        assert "critical update" in args[1]

    def test_voice_dry_run_forwarded(self):
        wa_msg = _make_wa_msg(status="sent", message_id="SMXXX")
        with patch("agents.director.send_whatsapp_summary", return_value=wa_msg), \
             patch("agents.director.is_whatsapp_read", return_value=False), \
             patch("agents.director.alert_owner_by_voice") as mock_voice:
            end_of_day_sequence(self.tenant, "s", dry_run=True, _wa_wait_seconds=0)
        _, kwargs = mock_voice.call_args
        assert kwargs.get("dry_run") is True


# ---------------------------------------------------------------------------
# run_daily
# ---------------------------------------------------------------------------

class TestRunDaily:
    def setup_method(self):
        self.tenant = _make_tenant()
        _mock_crewai.reset_mock(side_effect=True)
        _mock_langchain_anthropic.reset_mock(side_effect=True)
        _mock_jobs.reset_mock(side_effect=True)
        _mock_jobs.build_daily_tasks.return_value = ["task1"]
        self._wa_msg = _make_wa_msg(status="dry_run", message_id=None)

    def _run(self, dry_run=None):
        with patch("agents.director.send_whatsapp_summary", return_value=self._wa_msg), \
             patch("agents.director.is_whatsapp_read", return_value=True), \
             patch("agents.director.alert_owner_by_voice"):
            return run_daily(self.tenant, dry_run=dry_run)

    def test_returns_string(self):
        assert isinstance(self._run(), str)

    def test_builds_four_agents(self):
        self._run()
        assert _mock_crewai.Agent.call_count == 4

    def test_calls_build_daily_tasks(self):
        self._run()
        _mock_jobs.build_daily_tasks.assert_called_once()

    def test_build_daily_tasks_receives_tenant_config(self):
        self._run()
        args, _ = _mock_jobs.build_daily_tasks.call_args
        assert args[0] is self.tenant

    def test_build_daily_tasks_receives_agents_dict(self):
        self._run()
        args, _ = _mock_jobs.build_daily_tasks.call_args
        agents_arg = args[1]
        assert isinstance(agents_arg, dict)
        assert "director" in agents_arg

    def test_crew_kickoff_called(self):
        self._run()
        _mock_crewai.Crew.return_value.kickoff.assert_called_once()

    def test_result_is_kickoff_output_as_str(self):
        _mock_crewai.Crew.return_value.kickoff.return_value = "kickoff result"
        result = self._run()
        assert result == "kickoff result"

    def test_crew_uses_hierarchical_process(self):
        self._run()
        _, kwargs = _mock_crewai.Crew.call_args
        assert kwargs["process"] == _mock_crewai.Process.hierarchical

    def test_end_of_day_called_with_kickoff_result(self):
        _mock_crewai.Crew.return_value.kickoff.return_value = "the summary"
        with patch("agents.director.send_whatsapp_summary", return_value=self._wa_msg) as mock_wa, \
             patch("agents.director.is_whatsapp_read", return_value=True), \
             patch("agents.director.alert_owner_by_voice"):
            run_daily(self.tenant)
        args, _ = mock_wa.call_args
        assert args[1] == "the summary"

    def test_dry_run_forwarded_to_end_of_day(self):
        with patch("agents.director.send_whatsapp_summary", return_value=self._wa_msg) as mock_wa, \
             patch("agents.director.is_whatsapp_read", return_value=True), \
             patch("agents.director.alert_owner_by_voice"):
            run_daily(self.tenant, dry_run=True)
        _, kwargs = mock_wa.call_args
        assert kwargs["dry_run"] is True
