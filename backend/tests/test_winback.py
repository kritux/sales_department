"""
Tests for backend/agents/postventa/winback.py.

Mock strategy:
  crewai / langchain* injected via sys.modules.
  send_email and query_rag patched per-test.

Coverage:
  - get_winback_candidates: 90-day threshold, status filter, ordering
  - get_close_lost_candidates: 97-day threshold
  - _render_winback_email: EN / ES templates, RAG context injection
  - run_winback: email sent, error path, close_lost marking
  - build_winback_agent: instantiation
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inject heavy mocks
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
from agents.postventa.winback import (
    _WINBACK_WAIT_DAYS,
    _CLOSE_LOST_DAYS,
    _render_winback_email,
    get_winback_candidates,
    get_close_lost_candidates,
    run_winback,
    build_winback_agent,
    WinbackResult,
    LeadWinbackResult,
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
    )
    defaults.update(kw)
    return TenantConfig(**defaults)


def _make_lead(
    status: str = "no_response",
    days_since_contact: int = 90,
    score: int = 75,
    **kw,
) -> Lead:
    now_str = _NOW.isoformat()
    last_contact = _NOW - timedelta(days=days_since_contact)
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
        score=score,
        status=status,
        last_contact_at=last_contact.isoformat(),
        notes="",
        created_at=now_str,
        updated_at=now_str,
    )
    defaults.update(kw)
    return Lead(**defaults)


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_crewai.reset_mock(side_effect=True)
    _mock_langchain_anthropic.reset_mock(side_effect=True)
    sys.modules["crewai"] = _mock_crewai
    sys.modules["langchain_anthropic"] = _mock_langchain_anthropic
    yield


# ---------------------------------------------------------------------------
# get_winback_candidates
# ---------------------------------------------------------------------------


class TestGetWinbackCandidates:
    def test_qualifies_90_day_no_response(self):
        lead = _make_lead(status="no_response", days_since_contact=90)
        result = get_winback_candidates([lead], now=_NOW)
        assert len(result) == 1

    def test_excludes_recent_no_response(self):
        lead = _make_lead(status="no_response", days_since_contact=89)
        assert get_winback_candidates([lead], now=_NOW) == []

    def test_excludes_active_statuses(self):
        for status in ("new", "contacted", "responded", "meeting_set"):
            lead = _make_lead(status=status, days_since_contact=95)
            assert get_winback_candidates([lead], now=_NOW) == [], f"failed for {status}"

    def test_excludes_past_close_lost_window(self):
        # 97+ days → close_lost territory, not winback
        lead = _make_lead(status="no_response", days_since_contact=97)
        assert get_winback_candidates([lead], now=_NOW) == []

    def test_excludes_null_last_contact(self):
        lead = _make_lead(status="no_response", days_since_contact=95, last_contact_at=None)
        assert get_winback_candidates([lead], now=_NOW) == []

    def test_sorted_by_score_descending(self):
        low = _make_lead(id="low",  score=40, days_since_contact=91)
        high = _make_lead(id="high", score=90, days_since_contact=91)
        result = get_winback_candidates([low, high], now=_NOW)
        assert result[0].id == "high"

    def test_custom_wait_days(self):
        lead = _make_lead(status="no_response", days_since_contact=30)
        # With wait_days=30, this lead qualifies
        result = get_winback_candidates([lead], wait_days=30, now=_NOW)
        assert len(result) == 1

    def test_empty_list_returns_empty(self):
        assert get_winback_candidates([], now=_NOW) == []

    def test_boundary_exactly_90_days_qualifies(self):
        lead = _make_lead(status="no_response", days_since_contact=90)
        assert len(get_winback_candidates([lead], now=_NOW)) == 1

    def test_boundary_exactly_96_days_qualifies(self):
        # 96 days: >= 90 (wait) and < 97 (close_lost cutoff) → winback candidate
        lead = _make_lead(status="no_response", days_since_contact=96)
        assert len(get_winback_candidates([lead], now=_NOW)) == 1


# ---------------------------------------------------------------------------
# get_close_lost_candidates
# ---------------------------------------------------------------------------


class TestGetCloseLostCandidates:
    def test_97_days_qualifies(self):
        lead = _make_lead(status="no_response", days_since_contact=97)
        assert len(get_close_lost_candidates([lead], now=_NOW)) == 1

    def test_96_days_does_not_qualify(self):
        lead = _make_lead(status="no_response", days_since_contact=96)
        assert get_close_lost_candidates([lead], now=_NOW) == []

    def test_only_no_response_status(self):
        lead = _make_lead(status="contacted", days_since_contact=100)
        assert get_close_lost_candidates([lead], now=_NOW) == []

    def test_null_last_contact_excluded(self):
        lead = _make_lead(status="no_response", days_since_contact=100, last_contact_at=None)
        assert get_close_lost_candidates([lead], now=_NOW) == []


# ---------------------------------------------------------------------------
# _render_winback_email
# ---------------------------------------------------------------------------


class TestRenderWinbackEmail:
    def test_en_subject_mentions_checking_in(self):
        lead = _make_lead()
        tc = _make_tenant(language="en")
        subj, body = _render_winback_email(lead, tc, "")
        assert "Checking back in" in subj or "checking" in subj.lower()

    def test_es_subject_in_spanish(self):
        lead = _make_lead()
        tc = _make_tenant(language="es")
        subj, body = _render_winback_email(lead, tc, "")
        assert "contacto" in subj.lower() or "Siguiendo" in subj or "contacto" in body.lower()

    def test_rag_context_injected_into_body(self):
        lead = _make_lead()
        tc = _make_tenant(language="en")
        subj, body = _render_winback_email(lead, tc, "NEW SERVICES CONTEXT")
        assert "NEW SERVICES CONTEXT" in body

    def test_fallback_when_no_rag(self):
        lead = _make_lead(category="Plumber")
        tc = _make_tenant(language="en")
        subj, body = _render_winback_email(lead, tc, "")
        assert "Plumber" in body

    def test_sender_name_in_body(self):
        lead = _make_lead()
        tc = _make_tenant(sender_name="Maria Sanchez")
        subj, body = _render_winback_email(lead, tc, "")
        assert "Maria Sanchez" in body

    def test_lead_company_name_in_body(self):
        lead = _make_lead(company_name="TexBuild LLC")
        tc = _make_tenant()
        subj, body = _render_winback_email(lead, tc, "")
        assert "TexBuild LLC" in body


# ---------------------------------------------------------------------------
# run_winback
# ---------------------------------------------------------------------------


class TestRunWinbackDryRun:
    def test_sends_email_to_candidate(self):
        lead = _make_lead(status="no_response", days_since_contact=92)
        with patch("agents.postventa.winback.send_email", return_value=MagicMock()), \
             patch("agents.postventa.winback.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_winback([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.emails_sent == 1
        assert result.candidates_found == 1

    def test_result_marks_status_contacted(self):
        lead = _make_lead(status="no_response", days_since_contact=92)
        with patch("agents.postventa.winback.send_email", return_value=MagicMock()), \
             patch("agents.postventa.winback.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_winback([lead], _make_tenant(), dry_run=True, now=_NOW)
        email_results = [r for r in result.results if r.action == "email_sent"]
        assert email_results[0].mark_status == "contacted"

    def test_excludes_non_candidates(self):
        active = _make_lead(id="active", status="new", days_since_contact=92)
        with patch("agents.postventa.winback.send_email", return_value=MagicMock()), \
             patch("agents.postventa.winback.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_winback([active], _make_tenant(), dry_run=True, now=_NOW)
        assert result.emails_sent == 0
        assert result.candidates_found == 0

    def test_close_lost_leads_marked(self):
        old = _make_lead(id="old", status="no_response", days_since_contact=100)
        with patch("agents.postventa.winback.send_email", return_value=MagicMock()), \
             patch("agents.postventa.winback.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_winback([old], _make_tenant(), dry_run=True, now=_NOW)
        assert result.close_lost_marked == 1
        close_results = [r for r in result.results if r.action == "close_lost_marked"]
        assert close_results[0].mark_status == "closed_lost"

    def test_error_in_send_captured(self):
        lead = _make_lead(status="no_response", days_since_contact=92)
        with patch("agents.postventa.winback.send_email", side_effect=ValueError("bad email")), \
             patch("agents.postventa.winback.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_winback([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert result.emails_sent == 0
        err = [r for r in result.results if r.action == "error"]
        assert len(err) == 1
        assert "bad email" in err[0].reason

    def test_tenant_id_in_result(self):
        result = run_winback([], _make_tenant(tenant_id="tenant_007"), dry_run=True, now=_NOW)
        assert result.tenant_id == "tenant_007"

    def test_rag_context_used_when_found(self):
        lead = _make_lead(status="no_response", days_since_contact=92)
        sent_bodies = []

        def capture_send(lead, tenant_config, subject, body, dry_run=None):
            sent_bodies.append(body)
            return MagicMock()

        with patch("agents.postventa.winback.send_email", side_effect=capture_send), \
             patch("agents.postventa.winback.query_rag", return_value=MagicMock(
                 found=True, context="RAG CONTEXT HERE"
             )):
            run_winback([lead], _make_tenant(), dry_run=True, now=_NOW)
        assert any("RAG CONTEXT HERE" in b for b in sent_bodies)

    def test_multiple_candidates_all_receive_emails(self):
        leads = [
            _make_lead(id="a", status="no_response", days_since_contact=91),
            _make_lead(id="b", status="no_response", days_since_contact=93),
        ]
        with patch("agents.postventa.winback.send_email", return_value=MagicMock()), \
             patch("agents.postventa.winback.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_winback(leads, _make_tenant(), dry_run=True, now=_NOW)
        assert result.emails_sent == 2

    def test_mixed_leads_only_candidates_emailed(self):
        leads = [
            _make_lead(id="winback", status="no_response", days_since_contact=92),
            _make_lead(id="active",  status="new",         days_since_contact=92),
            _make_lead(id="old",     status="no_response", days_since_contact=100),
        ]
        with patch("agents.postventa.winback.send_email", return_value=MagicMock()), \
             patch("agents.postventa.winback.query_rag", return_value=MagicMock(found=False, context="")):
            result = run_winback(leads, _make_tenant(), dry_run=True, now=_NOW)
        assert result.emails_sent == 1
        assert result.close_lost_marked == 1


# ---------------------------------------------------------------------------
# build_winback_agent
# ---------------------------------------------------------------------------


class TestBuildWinbackAgent:
    def test_returns_agent(self):
        assert build_winback_agent(_make_tenant()) is not None

    def test_uses_crewai(self):
        build_winback_agent(_make_tenant())
        assert _mock_crewai.Agent.called

    def test_role_is_winback_specialist(self):
        build_winback_agent(_make_tenant())
        _, kwargs = _mock_crewai.Agent.call_args
        assert "WinBack Specialist" in kwargs.get("role", "")

    def test_no_delegation(self):
        build_winback_agent(_make_tenant())
        _, kwargs = _mock_crewai.Agent.call_args
        assert kwargs.get("allow_delegation") is False

    def test_has_tool(self):
        build_winback_agent(_make_tenant())
        _, kwargs = _mock_crewai.Agent.call_args
        assert len(kwargs.get("tools", [])) >= 1
