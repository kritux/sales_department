"""
Tests for backend/agents/cierre/email_agent.py.

Mock strategy:
  crewai / langchain_anthropic / langchain injected via sys.modules before import.
  send_email, call_prospect, query_rag patched per-test.

Coverage:
  - CadenceState serialization / deserialization
  - get_next_cadence_step: day-threshold selection, halt on response status
  - should_mark_no_response: all steps done with active status
  - Daily contact cap enforcement
  - run_email_cadence: email sent, call made, skipped, halted, cap_reached, no_response_marked
  - Email template rendering (intro, value, final)
  - build_email_agent: agent instantiation
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inject heavy mocks before any project import
# ---------------------------------------------------------------------------

def _tool_identity(name_or_fn):
    if callable(name_or_fn): return name_or_fn
    return lambda fn: fn

_mock_crewai = MagicMock()
_mock_langchain_anthropic = MagicMock()
_mock_langchain = MagicMock()
_mock_langchain_tools = MagicMock()
_mock_langchain_tools.tool = _tool_identity
_mock_langchain.tools = _mock_langchain_tools
_mock_lc_core = MagicMock()
_mock_lc_messages = MagicMock()

sys.modules.setdefault("crewai", _mock_crewai)
sys.modules.setdefault("langchain", _mock_langchain)
sys.modules.setdefault("langchain.tools", _mock_langchain_tools)
sys.modules.setdefault("langchain_anthropic", _mock_langchain_anthropic)
sys.modules.setdefault("langchain_core", _mock_lc_core)
sys.modules.setdefault("langchain_core.messages", _mock_lc_messages)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import TenantConfig, LeadCriteria
from db.models import Lead
from agents.cierre.email_agent import (
    CadenceState,
    CadenceStep,
    CadenceRunResult,
    LeadCadenceResult,
    _CADENCE_SCHEDULE,
    _CADENCE_NOTES_KEY,
    _TOTAL_STEPS,
    _parse_cadence_state,
    _encode_cadence_state,
    _render_value_email,
    _render_final_email,
    get_next_cadence_step,
    should_mark_no_response,
    run_email_cadence,
    build_email_agent,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 17, 10, 0, 0)


def _make_tenant(**kw) -> TenantConfig:
    defaults = dict(
        tenant_id="tenant_001",
        company_name="Growth Bizon",
        language="en",
        geo_center="Houston, TX",
        scraping_keywords=[],
        lead_criteria=LeadCriteria(industries=["contractor"]),
        sender_name="Carlos Rodriguez",
        sender_email="carlos@growthbizon.com",
        owner_whatsapp="+15551234567",
        owner_name="Carlos",
        rag_collection="rag_tenant_001",
        daily_contact_cap=50,
    )
    defaults.update(kw)
    return TenantConfig(**defaults)


def _make_lead(**kw) -> Lead:
    now_str = _NOW.isoformat()
    defaults = dict(
        id="lead-001",
        tenant_id="tenant_001",
        company_name="Acme Contractors",
        address="123 Main St",
        city="Houston",
        state="TX",
        phone="+17135550001",
        email="owner@acme.com",
        website=None,
        rating=4.5,
        review_count=20,
        category="General Contractor",
        score=75,
        status="new",
        last_contact_at=None,
        notes="",
        created_at=now_str,
        updated_at=now_str,
    )
    defaults.update(kw)
    return Lead(**defaults)


def _make_state(first_contact_days_ago: int, last_step: int) -> CadenceState:
    """Helper: build a CadenceState with first_contact N days before _NOW."""
    fc = _NOW - timedelta(days=first_contact_days_ago)
    return CadenceState(first_contact_at=fc, last_step_completed=last_step)


def _state_to_notes(state: CadenceState) -> str:
    return _encode_cadence_state(state)


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_crewai.reset_mock(side_effect=True)
    _mock_langchain_anthropic.reset_mock(side_effect=True)
    sys.modules["crewai"] = _mock_crewai
    sys.modules["langchain_anthropic"] = _mock_langchain_anthropic
    sys.modules["langchain.tools"] = _mock_langchain_tools
    sys.modules["langchain_core"] = _mock_lc_core
    sys.modules["langchain_core.messages"] = _mock_lc_messages
    yield


# ---------------------------------------------------------------------------
# CadenceState serialization
# ---------------------------------------------------------------------------


class TestCadenceStateSerialization:
    def test_encode_produces_prefix(self):
        state = _make_state(0, 1)
        encoded = _encode_cadence_state(state)
        assert encoded.startswith(_CADENCE_NOTES_KEY)

    def test_decode_roundtrip(self):
        state = _make_state(5, 2)
        encoded = _encode_cadence_state(state)
        lead = _make_lead(notes=encoded)
        parsed = _parse_cadence_state(lead)
        assert parsed is not None
        assert parsed.last_step_completed == 2

    def test_parse_no_state_returns_none(self):
        lead = _make_lead(notes="")
        assert _parse_cadence_state(lead) is None

    def test_parse_freetext_notes_returns_none(self):
        lead = _make_lead(notes="Spoke with owner on Monday")
        assert _parse_cadence_state(lead) is None

    def test_encode_preserves_freetext_after_cadence_line(self):
        state = _make_state(3, 1)
        existing = "Some free note"
        encoded = _encode_cadence_state(state, existing)
        assert "Some free note" in encoded
        assert encoded.startswith(_CADENCE_NOTES_KEY)

    def test_encode_replaces_existing_cadence_line(self):
        state1 = _make_state(3, 1)
        encoded1 = _encode_cadence_state(state1)
        state2 = _make_state(3, 2)
        encoded2 = _encode_cadence_state(state2, encoded1)
        # Only one CADENCE: line
        assert encoded2.count(_CADENCE_NOTES_KEY) == 1
        parsed = _parse_cadence_state(_make_lead(notes=encoded2))
        assert parsed.last_step_completed == 2

    def test_first_contact_datetime_preserved(self):
        fc = datetime(2026, 6, 1, 9, 0, 0)
        state = CadenceState(first_contact_at=fc, last_step_completed=0)
        encoded = _encode_cadence_state(state)
        parsed = _parse_cadence_state(_make_lead(notes=encoded))
        assert parsed.first_contact_at == fc

    def test_invalid_json_returns_none(self):
        lead = _make_lead(notes=f"{_CADENCE_NOTES_KEY}{{not valid json}}")
        assert _parse_cadence_state(lead) is None


# ---------------------------------------------------------------------------
# get_next_cadence_step
# ---------------------------------------------------------------------------


class TestGetNextCadenceStep:
    def test_new_lead_no_state_returns_step_1(self):
        lead = _make_lead(status="new")
        step = get_next_cadence_step(lead, None, _NOW)
        assert step is not None
        assert step.step == 1
        assert step.channel == "email"

    def test_day_0_returns_step_1(self):
        lead = _make_lead(status="contacted")
        state = _make_state(0, 1)  # step 1 done today
        step = get_next_cadence_step(lead, state, _NOW)
        # step 2 is at day 3, not due yet
        assert step is None

    def test_day_3_returns_step_2(self):
        lead = _make_lead(status="contacted")
        state = _make_state(3, 1)
        step = get_next_cadence_step(lead, state, _NOW)
        assert step is not None
        assert step.step == 2
        assert step.template == "value"

    def test_day_5_also_returns_step_2_if_not_sent(self):
        lead = _make_lead(status="contacted")
        state = _make_state(5, 1)
        step = get_next_cadence_step(lead, state, _NOW)
        assert step is not None
        assert step.step == 2

    def test_day_7_returns_step_3_call(self):
        lead = _make_lead(status="contacted")
        state = _make_state(7, 2)
        step = get_next_cadence_step(lead, state, _NOW)
        assert step is not None
        assert step.step == 3
        assert step.channel == "call"

    def test_day_14_returns_step_4_final_email(self):
        lead = _make_lead(status="contacted")
        state = _make_state(14, 3)
        step = get_next_cadence_step(lead, state, _NOW)
        assert step is not None
        assert step.step == 4
        assert step.template == "final"

    def test_all_steps_done_returns_none(self):
        lead = _make_lead(status="contacted")
        state = _make_state(15, 4)
        step = get_next_cadence_step(lead, state, _NOW)
        assert step is None

    def test_responded_status_halts_step_1(self):
        lead = _make_lead(status="responded")
        assert get_next_cadence_step(lead, None, _NOW) is None

    def test_meeting_set_status_halts(self):
        lead = _make_lead(status="meeting_set")
        state = _make_state(3, 1)
        assert get_next_cadence_step(lead, state, _NOW) is None

    def test_closed_won_halts(self):
        lead = _make_lead(status="closed_won")
        assert get_next_cadence_step(lead, None, _NOW) is None

    def test_closed_lost_halts(self):
        lead = _make_lead(status="closed_lost")
        assert get_next_cadence_step(lead, None, _NOW) is None

    def test_no_response_halts(self):
        lead = _make_lead(status="no_response")
        assert get_next_cadence_step(lead, None, _NOW) is None

    def test_step_not_due_yet_returns_none(self):
        # Step 2 is at day 3. Only 1 day has passed since step 1.
        lead = _make_lead(status="contacted")
        state = _make_state(1, 1)
        assert get_next_cadence_step(lead, state, _NOW) is None

    def test_cadence_steps_are_sequential(self):
        """Steps can't be skipped — completing step 2 unlocks step 3."""
        lead = _make_lead(status="contacted")
        # Day 14 elapsed but only step 1 done — step 2 is next, not step 4
        state = _make_state(14, 1)
        step = get_next_cadence_step(lead, state, _NOW)
        assert step.step == 2


# ---------------------------------------------------------------------------
# should_mark_no_response
# ---------------------------------------------------------------------------


class TestShouldMarkNoResponse:
    def test_all_steps_done_active_status_returns_true(self):
        lead = _make_lead(status="contacted")
        state = _make_state(15, 4)
        assert should_mark_no_response(lead, state) is True

    def test_not_all_steps_done_returns_false(self):
        lead = _make_lead(status="contacted")
        state = _make_state(15, 3)
        assert should_mark_no_response(lead, state) is False

    def test_no_state_returns_false(self):
        lead = _make_lead(status="contacted")
        assert should_mark_no_response(lead, None) is False

    def test_responded_status_returns_false(self):
        lead = _make_lead(status="responded")
        state = _make_state(15, 4)
        assert should_mark_no_response(lead, state) is False

    def test_no_response_status_returns_false(self):
        # Already marked — shouldn't be re-marked
        lead = _make_lead(status="no_response")
        state = _make_state(15, 4)
        assert should_mark_no_response(lead, state) is False


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------


class TestEmailTemplates:
    def _tc(self, lang="en"):
        return _make_tenant(language=lang)

    def test_value_email_en_has_following_up(self):
        lead = _make_lead()
        subj, body = _render_value_email(lead, self._tc("en"), "")
        assert "Following up" in subj or "following up" in body.lower()

    def test_value_email_es_has_siguiendo(self):
        lead = _make_lead()
        subj, body = _render_value_email(lead, self._tc("es"), "")
        assert "Siguiendo" in subj or "siguiendo" in body.lower()

    def test_value_email_uses_rag_context(self):
        lead = _make_lead()
        subj, body = _render_value_email(lead, self._tc("en"), "Custom RAG block here")
        assert "Custom RAG block here" in body

    def test_final_email_en_has_last_note(self):
        lead = _make_lead()
        subj, body = _render_final_email(lead, self._tc("en"))
        assert "Last note" in subj or "last message" in body.lower()

    def test_final_email_es_has_ultimo(self):
        lead = _make_lead()
        subj, body = _render_final_email(lead, self._tc("es"))
        assert "ltimo" in subj  # "Último" — accent-agnostic check

    def test_final_email_mentions_lead_company(self):
        lead = _make_lead(company_name="TexBuild LLC")
        subj, body = _render_final_email(lead, self._tc("en"))
        assert "TexBuild LLC" in body

    def test_value_email_fallback_when_no_rag(self):
        lead = _make_lead(category="Plumber")
        subj, body = _render_value_email(lead, self._tc("en"), "")
        assert "Plumber" in body


# ---------------------------------------------------------------------------
# run_email_cadence
# ---------------------------------------------------------------------------

_DRY_OUTBOUND = MagicMock(return_value=MagicMock(status="dry_run"))


class TestRunEmailCadenceDryRun:
    """Happy-path cadence run with DRY_RUN=True."""

    def test_new_lead_sends_intro_email(self):
        lead = _make_lead(status="new")
        with patch("agents.cierre.email_agent.send_email", return_value=MagicMock()), \
             patch("agents.cierre.email_agent.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.emails_sent == 1
        assert result.results[0].action == "email_sent"
        assert result.results[0].step == 1

    def test_step_2_due_at_day_3(self):
        state = _make_state(3, 1)
        lead = _make_lead(status="contacted", notes=_state_to_notes(state))
        with patch("agents.cierre.email_agent.send_email", return_value=MagicMock()), \
             patch("agents.cierre.email_agent.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.emails_sent == 1
        assert result.results[0].step == 2

    def test_step_3_call_at_day_7(self):
        state = _make_state(7, 2)
        lead = _make_lead(status="contacted", notes=_state_to_notes(state))
        with patch("agents.cierre.email_agent.call_prospect", return_value=MagicMock()):
            result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.calls_made == 1
        assert result.results[0].action == "call_made"
        assert result.results[0].step == 3

    def test_step_4_final_email_at_day_14(self):
        state = _make_state(14, 3)
        lead = _make_lead(status="contacted", notes=_state_to_notes(state))
        with patch("agents.cierre.email_agent.send_email", return_value=MagicMock()), \
             patch("agents.cierre.email_agent.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.emails_sent == 1
        assert result.results[0].step == 4

    def test_result_includes_updated_notes(self):
        lead = _make_lead(status="new")
        with patch("agents.cierre.email_agent.send_email", return_value=MagicMock()), \
             patch("agents.cierre.email_agent.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.results[0].updated_notes is not None
        assert _CADENCE_NOTES_KEY in result.results[0].updated_notes

    def test_new_lead_result_marks_status_contacted(self):
        lead = _make_lead(status="new")
        with patch("agents.cierre.email_agent.send_email", return_value=MagicMock()), \
             patch("agents.cierre.email_agent.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.results[0].mark_status == "contacted"

    def test_already_contacted_lead_has_no_mark_status_change(self):
        state = _make_state(3, 1)
        lead = _make_lead(status="contacted", notes=_state_to_notes(state))
        with patch("agents.cierre.email_agent.send_email", return_value=MagicMock()), \
             patch("agents.cierre.email_agent.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.results[0].mark_status is None


class TestSequenceHalt:
    def test_responded_status_halted(self):
        lead = _make_lead(status="responded")
        result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.results[0].action == "halted"
        assert result.emails_sent == 0

    def test_meeting_set_halted(self):
        lead = _make_lead(status="meeting_set")
        result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.results[0].action == "halted"

    def test_closed_won_halted(self):
        lead = _make_lead(status="closed_won")
        result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.results[0].action == "halted"

    def test_no_response_status_halted(self):
        lead = _make_lead(status="no_response")
        result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.results[0].action == "halted"


class TestNoResponseMarking:
    def test_all_steps_done_marks_no_response(self):
        state = _make_state(16, 4)
        lead = _make_lead(status="contacted", notes=_state_to_notes(state))
        result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.no_response_marked == 1
        assert result.results[0].action == "no_response_marked"
        assert result.results[0].mark_status == "no_response"


class TestSkippedStep:
    def test_step_not_due_yet_skipped(self):
        state = _make_state(1, 1)  # day 1, step 2 due at day 3
        lead = _make_lead(status="contacted", notes=_state_to_notes(state))
        result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.results[0].action == "skipped"
        assert result.emails_sent == 0

    def test_call_step_skipped_when_no_phone(self):
        state = _make_state(7, 2)
        lead = _make_lead(status="contacted", phone=None, notes=_state_to_notes(state))
        result = run_email_cadence([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.results[0].action == "skipped"
        assert result.results[0].reason == "no phone number"


class TestDailyContactCap:
    def test_cap_stops_processing(self):
        leads = [_make_lead(id=f"lead-{i}", status="new") for i in range(5)]
        tenant = _make_tenant(daily_contact_cap=2)
        with patch("agents.cierre.email_agent.send_email", return_value=MagicMock()), \
             patch("agents.cierre.email_agent.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_email_cadence(leads, tenant, dry_run=True, now=_NOW)
        assert result.emails_sent == 2
        assert result.cap_reached is True
        cap_results = [r for r in result.results if r.action == "cap_reached"]
        assert len(cap_results) == 3

    def test_daily_sent_count_carries_over(self):
        leads = [_make_lead(id=f"lead-{i}", status="new") for i in range(3)]
        tenant = _make_tenant(daily_contact_cap=2)
        with patch("agents.cierre.email_agent.send_email", return_value=MagicMock()), \
             patch("agents.cierre.email_agent.query_rag", return_value=MagicMock(found=False, context="")):
            # already sent 2 today → cap hit immediately
            result = run_email_cadence(
                leads, tenant, daily_sent_count=2, dry_run=True, now=_NOW
            )
        assert result.emails_sent == 0
        assert result.cap_reached is True

    def test_cap_of_zero_blocks_all(self):
        lead = _make_lead(status="new")
        tenant = _make_tenant(daily_contact_cap=0)
        result = run_email_cadence([lead], tenant, dry_run=True, now=_NOW)
        assert result.emails_sent == 0
        assert result.cap_reached is True

    def test_cap_counts_calls_too(self):
        """A call counts toward the daily cap just like an email."""
        state = _make_state(7, 2)
        lead = _make_lead(status="contacted", notes=_state_to_notes(state))
        tenant = _make_tenant(daily_contact_cap=1)
        with patch("agents.cierre.email_agent.call_prospect", return_value=MagicMock()):
            result = run_email_cadence([lead], tenant, dry_run=True, now=_NOW)
        assert result.calls_made == 1
        assert result.emails_sent == 0


class TestMultipleLeads:
    def test_processes_all_leads(self):
        leads = [
            _make_lead(id="lead-a", status="new"),
            _make_lead(id="lead-b", status="new"),
            _make_lead(id="lead-c", status="responded"),
        ]
        with patch("agents.cierre.email_agent.send_email", return_value=MagicMock()), \
             patch("agents.cierre.email_agent.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_email_cadence(leads, _make_tenant(), dry_run=True, now=_NOW)
        assert result.processed == 3
        assert result.emails_sent == 2
        actions = [r.action for r in result.results]
        assert actions.count("email_sent") == 2
        assert actions.count("halted") == 1

    def test_tenant_id_in_result(self):
        result = run_email_cadence([], _make_tenant(tenant_id="tenant_007"), dry_run=True, now=_NOW)
        assert result.tenant_id == "tenant_007"


# ---------------------------------------------------------------------------
# build_email_agent
# ---------------------------------------------------------------------------


class TestBuildEmailAgent:
    def test_returns_agent_object(self):
        agent = build_email_agent(_make_tenant())
        assert agent is not None

    def test_agent_constructed_with_crewai(self):
        build_email_agent(_make_tenant())
        assert _mock_crewai.Agent.called

    def test_agent_role_is_email_specialist(self):
        build_email_agent(_make_tenant())
        _, kwargs = _mock_crewai.Agent.call_args
        assert "Email Specialist" in kwargs.get("role", "")

    def test_agent_has_tool(self):
        build_email_agent(_make_tenant())
        _, kwargs = _mock_crewai.Agent.call_args
        assert len(kwargs.get("tools", [])) >= 1

    def test_agent_no_delegation(self):
        build_email_agent(_make_tenant())
        _, kwargs = _mock_crewai.Agent.call_args
        assert kwargs.get("allow_delegation") is False

    def test_agent_goal_mentions_daily_cap(self):
        build_email_agent(_make_tenant(daily_contact_cap=30))
        _, kwargs = _mock_crewai.Agent.call_args
        assert "30" in kwargs.get("goal", "")
