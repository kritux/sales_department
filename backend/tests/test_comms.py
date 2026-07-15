"""
Tests for backend/tools/email_tool.py.

All tests run without network access — resend is mocked via sys.modules injection
before the module is imported, keeping the suite fast and hermetic.

Coverage:
  - OutboundMessage model (Contract 5)
  - _validate_email regex
  - _to_html paragraph converter
  - render_email EN / ES templates
  - send_email dry-run path
  - send_email invalid-address validation
  - send_email production success path
  - send_email production failure path
  - _send_with_retry backoff behaviour
"""

import sys
import logging
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Inject resend mock BEFORE importing email_tool so the lazy `import resend`
# inside _send_with_retry picks up our mock.
# ---------------------------------------------------------------------------

_mock_resend = MagicMock()
sys.modules.setdefault("resend", _mock_resend)

# Now safe to import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import TenantConfig, LeadCriteria
from db.models import Lead
from tools.email_tool import (
    OutboundMessage,
    _validate_email,
    _to_html,
    render_email,
    send_email,
    _send_with_retry,
    _MAX_RETRIES,
    _RETRY_BASE_SECONDS,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

NOW = datetime.utcnow().isoformat()


def _make_lead(**kwargs) -> Lead:
    defaults = dict(
        id="lead-001",
        tenant_id="tenant_001",
        company_name="Acme Contracting",
        address="123 Main St, Houston, TX 77001",
        city="Houston",
        state="TX",
        phone="+17135550001",
        email="owner@acme.com",
        website=None,
        rating=4.5,
        review_count=80,
        category="General Contractor",
        score=85,
        source="google_maps",
        status="new",
        last_contact_at=None,
        notes="",
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(kwargs)
    return Lead(**defaults)


def _make_tenant(**kwargs) -> TenantConfig:
    defaults = dict(
        tenant_id="tenant_001",
        company_name="Growth Bizon",
        language="en",
        geo_center="Houston, TX",
        lead_criteria=LeadCriteria(),
        sender_name="Sales Team",
        sender_email="sales@growthbizon.com",
        owner_whatsapp="+17135559999",
        owner_name="Owner",
        rag_collection="rag_tenant_001",
    )
    defaults.update(kwargs)
    return TenantConfig(**defaults)


@pytest.fixture(autouse=True)
def reset_resend_mock():
    """Reset resend mock state between tests, including side_effect on child mocks."""
    _mock_resend.reset_mock(side_effect=True)
    yield


# ---------------------------------------------------------------------------
# OutboundMessage model — Contract 5
# ---------------------------------------------------------------------------

class TestOutboundMessage:
    def test_status_sent(self):
        msg = OutboundMessage(
            tenant_id="t1", lead_id="l1", recipient="a@b.com",
            body="Hello", status="sent", dry_run=False,
        )
        assert msg.status == "sent"

    def test_status_failed(self):
        msg = OutboundMessage(
            tenant_id="t1", lead_id="l1", recipient="a@b.com",
            body="Hello", status="failed", dry_run=False,
        )
        assert msg.status == "failed"

    def test_status_dry_run(self):
        msg = OutboundMessage(
            tenant_id="t1", lead_id="l1", recipient="a@b.com",
            body="Hello", status="dry_run", dry_run=True,
        )
        assert msg.status == "dry_run"

    def test_channel_defaults_to_email(self):
        msg = OutboundMessage(
            tenant_id="t1", lead_id="l1", recipient="a@b.com",
            body="Hello", status="sent", dry_run=False,
        )
        assert msg.channel == "email"

    def test_subject_optional(self):
        msg = OutboundMessage(
            tenant_id="t1", lead_id="l1", recipient="a@b.com",
            body="Hello", status="sent", dry_run=False,
        )
        assert msg.subject is None

    def test_message_id_optional(self):
        msg = OutboundMessage(
            tenant_id="t1", lead_id="l1", recipient="a@b.com",
            body="Hello", status="sent", dry_run=False,
        )
        assert msg.message_id is None

    def test_sent_at_optional(self):
        msg = OutboundMessage(
            tenant_id="t1", lead_id="l1", recipient="a@b.com",
            body="Hello", status="sent", dry_run=False,
        )
        assert msg.sent_at is None

    def test_full_fields_accepted(self):
        ts = datetime.utcnow()
        msg = OutboundMessage(
            tenant_id="t1", lead_id="l1", channel="email",
            recipient="a@b.com", subject="Hi", body="Hello",
            sent_at=ts, status="sent", dry_run=False, message_id="msg-123",
        )
        assert msg.message_id == "msg-123"
        assert msg.sent_at == ts


# ---------------------------------------------------------------------------
# _validate_email
# ---------------------------------------------------------------------------

class TestValidateEmail:
    def test_valid_simple(self):
        assert _validate_email("user@example.com") is True

    def test_valid_subdomain(self):
        assert _validate_email("user@mail.example.com") is True

    def test_valid_plus_tag(self):
        assert _validate_email("user+tag@example.com") is True

    def test_valid_dot_in_local(self):
        assert _validate_email("first.last@example.com") is True

    def test_valid_hyphen_in_domain(self):
        assert _validate_email("user@my-company.com") is True

    def test_invalid_no_at(self):
        assert _validate_email("userexample.com") is False

    def test_invalid_no_domain(self):
        assert _validate_email("user@") is False

    def test_invalid_no_tld(self):
        assert _validate_email("user@example") is False

    def test_invalid_empty_string(self):
        assert _validate_email("") is False

    def test_invalid_whitespace_only(self):
        assert _validate_email("   ") is False

    def test_strips_whitespace_before_validating(self):
        assert _validate_email("  user@example.com  ") is True

    def test_invalid_double_at(self):
        assert _validate_email("user@@example.com") is False

    def test_invalid_space_in_address(self):
        assert _validate_email("user name@example.com") is False


# ---------------------------------------------------------------------------
# _to_html
# ---------------------------------------------------------------------------

class TestToHtml:
    def test_single_paragraph(self):
        result = _to_html("Hello world")
        assert result == "<p>Hello world</p>"

    def test_two_paragraphs(self):
        result = _to_html("First paragraph\n\nSecond paragraph")
        assert "<p>First paragraph</p>" in result
        assert "<p>Second paragraph</p>" in result

    def test_inline_newlines_become_br(self):
        result = _to_html("Line one\nLine two")
        assert "<br>" in result

    def test_strips_leading_trailing_whitespace(self):
        result = _to_html("  Hello  ")
        assert result == "<p>Hello</p>"

    def test_multi_paragraph_order(self):
        result = _to_html("A\n\nB\n\nC")
        a_pos = result.index("<p>A</p>")
        b_pos = result.index("<p>B</p>")
        c_pos = result.index("<p>C</p>")
        assert a_pos < b_pos < c_pos


# ---------------------------------------------------------------------------
# render_email — English
# ---------------------------------------------------------------------------

class TestRenderEmailEnglish:
    def setup_method(self):
        self.lead = _make_lead()
        self.tenant = _make_tenant(language="en")

    def test_returns_tuple(self):
        result = render_email(self.lead, self.tenant, "")
        assert isinstance(result, tuple) and len(result) == 2

    def test_subject_contains_company_name(self):
        subject, _ = render_email(self.lead, self.tenant, "")
        assert "Acme Contracting" in subject

    def test_subject_english_template(self):
        subject, _ = render_email(self.lead, self.tenant, "")
        assert "Quick question" in subject

    def test_body_contains_lead_company_name(self):
        _, body = render_email(self.lead, self.tenant, "")
        assert "Acme Contracting" in body

    def test_body_contains_sender_name(self):
        _, body = render_email(self.lead, self.tenant, "")
        assert "Sales Team" in body

    def test_body_contains_city(self):
        _, body = render_email(self.lead, self.tenant, "")
        assert "Houston" in body

    def test_body_contains_category(self):
        _, body = render_email(self.lead, self.tenant, "")
        assert "General Contractor" in body

    def test_rag_context_injected_when_provided(self):
        _, body = render_email(self.lead, self.tenant, "We doubled revenue for contractors.")
        assert "We doubled revenue for contractors." in body

    def test_fallback_used_when_no_rag_context(self):
        _, body = render_email(self.lead, self.tenant, "")
        assert "Growth Bizon" in body

    def test_empty_rag_context_triggers_fallback(self):
        _, body = render_email(self.lead, self.tenant, "")
        assert "General Contractor" in body  # fallback mentions the category


# ---------------------------------------------------------------------------
# render_email — Spanish
# ---------------------------------------------------------------------------

class TestRenderEmailSpanish:
    def setup_method(self):
        self.lead = _make_lead()
        self.tenant = _make_tenant(language="es")

    def test_subject_spanish_template(self):
        subject, _ = render_email(self.lead, self.tenant, "")
        assert "Pregunta rápida" in subject

    def test_body_spanish_greeting(self):
        _, body = render_email(self.lead, self.tenant, "")
        assert "Hola" in body

    def test_body_spanish_cta(self):
        _, body = render_email(self.lead, self.tenant, "")
        assert "15 minutos" in body

    def test_spanish_rag_context_injected(self):
        _, body = render_email(self.lead, self.tenant, "Duplicamos ingresos.")
        assert "Duplicamos ingresos." in body

    def test_spanish_fallback_mentions_category(self):
        _, body = render_email(self.lead, self.tenant, "")
        assert "General Contractor" in body


# ---------------------------------------------------------------------------
# send_email — dry-run path
# ---------------------------------------------------------------------------

class TestSendEmailDryRun:
    def setup_method(self):
        self.lead = _make_lead()
        self.tenant = _make_tenant()

    def test_dry_run_returns_outbound_message(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert isinstance(result, OutboundMessage)

    def test_dry_run_status_is_dry_run(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert result.status == "dry_run"

    def test_dry_run_flag_is_true(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert result.dry_run is True

    def test_dry_run_sent_at_is_none(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert result.sent_at is None

    def test_dry_run_message_id_is_none(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert result.message_id is None

    def test_dry_run_recipient_set(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert result.recipient == "owner@acme.com"

    def test_dry_run_subject_set(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert result.subject == "Subject"

    def test_dry_run_body_set(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert result.body == "Body"

    def test_dry_run_tenant_id_set(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert result.tenant_id == "tenant_001"

    def test_dry_run_lead_id_set(self):
        result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        assert result.lead_id == "lead-001"

    def test_dry_run_never_calls_resend(self):
        send_email(self.lead, self.tenant, "Subject", "Body", dry_run=True)
        _mock_resend.Emails.send.assert_not_called()

    def test_dry_run_via_settings_fallback(self):
        with patch("tools.email_tool.settings") as mock_settings:
            mock_settings.dry_run = True
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=None)
        assert result.status == "dry_run"


# ---------------------------------------------------------------------------
# send_email — email validation
# ---------------------------------------------------------------------------

class TestSendEmailValidation:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_missing_email_raises_value_error(self):
        lead = _make_lead(email=None)
        with pytest.raises(ValueError, match="Invalid or missing email"):
            send_email(lead, self.tenant, "S", "B", dry_run=True)

    def test_empty_string_email_raises_value_error(self):
        lead = _make_lead(email="")
        with pytest.raises(ValueError):
            send_email(lead, self.tenant, "S", "B", dry_run=True)

    def test_invalid_email_format_raises_value_error(self):
        lead = _make_lead(email="not-an-email")
        with pytest.raises(ValueError):
            send_email(lead, self.tenant, "S", "B", dry_run=True)

    def test_validation_runs_before_dry_run_check(self):
        """ValueError should raise even in dry-run mode."""
        lead = _make_lead(email="bad-email")
        with pytest.raises(ValueError):
            send_email(lead, self.tenant, "S", "B", dry_run=True)


# ---------------------------------------------------------------------------
# send_email — production success path
# ---------------------------------------------------------------------------

class TestSendEmailProductionSuccess:
    def setup_method(self):
        self.lead = _make_lead()
        self.tenant = _make_tenant()
        _mock_resend.Emails.send.return_value = {"id": "resend-msg-abc"}

    def test_returns_outbound_message(self):
        with patch("tools.email_tool.settings") as ms:
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert isinstance(result, OutboundMessage)

    def test_status_is_sent(self):
        with patch("tools.email_tool.settings") as ms:
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert result.status == "sent"

    def test_dry_run_flag_is_false(self):
        with patch("tools.email_tool.settings") as ms:
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert result.dry_run is False

    def test_message_id_populated(self):
        with patch("tools.email_tool.settings") as ms:
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert result.message_id == "resend-msg-abc"

    def test_sent_at_populated(self):
        with patch("tools.email_tool.settings") as ms:
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert isinstance(result.sent_at, datetime)

    def test_resend_called_once(self):
        with patch("tools.email_tool.settings") as ms:
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        _mock_resend.Emails.send.assert_called_once()

    def test_from_address_format(self):
        with patch("tools.email_tool.settings") as ms:
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        call_kwargs = _mock_resend.Emails.send.call_args[0][0]
        assert call_kwargs["from"] == "Sales Team <sales@growthbizon.com>"

    def test_to_address_correct(self):
        with patch("tools.email_tool.settings") as ms:
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        call_kwargs = _mock_resend.Emails.send.call_args[0][0]
        assert "owner@acme.com" in call_kwargs["to"]

    def test_html_body_sent(self):
        with patch("tools.email_tool.settings") as ms:
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        call_kwargs = _mock_resend.Emails.send.call_args[0][0]
        assert "<p>" in call_kwargs["html"]


# ---------------------------------------------------------------------------
# send_email — production failure path
# ---------------------------------------------------------------------------

class TestSendEmailProductionFailure:
    def setup_method(self):
        self.lead = _make_lead()
        self.tenant = _make_tenant()

    def test_api_failure_returns_failed_status(self):
        _mock_resend.Emails.send.side_effect = Exception("Resend timeout")
        with patch("tools.email_tool.settings") as ms, \
             patch("tools.email_tool.time.sleep"):
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert result.status == "failed"

    def test_api_failure_dry_run_is_false(self):
        _mock_resend.Emails.send.side_effect = Exception("err")
        with patch("tools.email_tool.settings") as ms, \
             patch("tools.email_tool.time.sleep"):
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert result.dry_run is False

    def test_api_failure_sent_at_is_none(self):
        _mock_resend.Emails.send.side_effect = Exception("err")
        with patch("tools.email_tool.settings") as ms, \
             patch("tools.email_tool.time.sleep"):
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert result.sent_at is None

    def test_api_failure_message_id_is_none(self):
        _mock_resend.Emails.send.side_effect = Exception("err")
        with patch("tools.email_tool.settings") as ms, \
             patch("tools.email_tool.time.sleep"):
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert result.message_id is None

    def test_does_not_raise_on_api_failure(self):
        _mock_resend.Emails.send.side_effect = Exception("network error")
        with patch("tools.email_tool.settings") as ms, \
             patch("tools.email_tool.time.sleep"):
            ms.dry_run = False
            ms.resend_api_key = "re_test_key"
            # Should not raise — returns OutboundMessage(status="failed")
            result = send_email(self.lead, self.tenant, "Subject", "Body", dry_run=False)
        assert result is not None


# ---------------------------------------------------------------------------
# _send_with_retry — backoff behaviour
# ---------------------------------------------------------------------------

class TestSendWithRetry:
    def test_success_on_first_attempt_returns_message_id(self):
        _mock_resend.Emails.send.return_value = {"id": "msg-001"}
        result = _send_with_retry("f@f.com", "t@t.com", "S", "<p>B</p>", "key")
        assert result == "msg-001"

    def test_success_on_first_attempt_calls_send_once(self):
        _mock_resend.Emails.send.return_value = {"id": "msg-001"}
        _send_with_retry("f@f.com", "t@t.com", "S", "<p>B</p>", "key")
        assert _mock_resend.Emails.send.call_count == 1

    def test_retry_on_failure_then_success(self):
        _mock_resend.Emails.send.side_effect = [
            Exception("fail 1"),
            {"id": "msg-retry"},
        ]
        with patch("tools.email_tool.time.sleep"):
            result = _send_with_retry("f@f.com", "t@t.com", "S", "<p>B</p>", "key")
        assert result == "msg-retry"

    def test_all_retries_exhausted_raises(self):
        _mock_resend.Emails.send.side_effect = Exception("always fails")
        with patch("tools.email_tool.time.sleep"), \
             pytest.raises(Exception, match="always fails"):
            _send_with_retry("f@f.com", "t@t.com", "S", "<p>B</p>", "key")

    def test_total_attempts_equals_max_retries_plus_one(self):
        _mock_resend.Emails.send.side_effect = Exception("fail")
        with patch("tools.email_tool.time.sleep"):
            try:
                _send_with_retry("f@f.com", "t@t.com", "S", "<p>B</p>", "key")
            except Exception:
                pass
        assert _mock_resend.Emails.send.call_count == _MAX_RETRIES + 1

    def test_backoff_delays_are_exponential(self):
        _mock_resend.Emails.send.side_effect = Exception("fail")
        sleep_calls = []
        with patch("tools.email_tool.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            try:
                _send_with_retry("f@f.com", "t@t.com", "S", "<p>B</p>", "key")
            except Exception:
                pass
        assert sleep_calls[0] == pytest.approx(_RETRY_BASE_SECONDS * 1)
        assert sleep_calls[1] == pytest.approx(_RETRY_BASE_SECONDS * 2)
        assert sleep_calls[2] == pytest.approx(_RETRY_BASE_SECONDS * 4)

    def test_no_sleep_after_last_attempt(self):
        """sleep should be called _MAX_RETRIES times, not _MAX_RETRIES+1."""
        _mock_resend.Emails.send.side_effect = Exception("fail")
        sleep_calls = []
        with patch("tools.email_tool.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            try:
                _send_with_retry("f@f.com", "t@t.com", "S", "<p>B</p>", "key")
            except Exception:
                pass
        assert len(sleep_calls) == _MAX_RETRIES

    def test_sets_api_key_before_send(self):
        _mock_resend.Emails.send.return_value = {"id": "x"}
        _send_with_retry("f@f.com", "t@t.com", "S", "<p>B</p>", "my_key")
        assert _mock_resend.api_key == "my_key"

    def test_missing_id_in_response_returns_empty_string(self):
        _mock_resend.Emails.send.return_value = {}
        result = _send_with_retry("f@f.com", "t@t.com", "S", "<p>B</p>", "key")
        assert result == ""
