"""
Tests for backend/tools/whatsapp_tool.py.

No network access — Twilio is mocked via sys.modules injection before
the module is imported, keeping the suite hermetic and fast.

Twilio mock structure:
  _mock_twilio_rest.Client(sid, token)  → _mock_client
  _mock_client.messages.create(...)     → _mock_message  (.sid)
  _mock_client.messages(sid).fetch()    → _mock_fetched  (.status)

Coverage:
  - _validate_phone E.164 regex
  - _whatsapp_addr scheme prefix
  - send_whatsapp_summary dry-run path
  - send_whatsapp_summary phone validation
  - send_whatsapp_summary production success
  - send_whatsapp_summary production failure
  - is_whatsapp_read dry-run path
  - is_whatsapp_read production (read / not-read / error)
  - _send_with_retry backoff behaviour
"""

import sys
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Inject Twilio mock BEFORE importing whatsapp_tool so lazy imports resolve
# to our controlled objects.
# ---------------------------------------------------------------------------

_mock_client = MagicMock()
_mock_twilio_rest = MagicMock()
_mock_twilio_rest.Client.return_value = _mock_client

sys.modules.setdefault("twilio", MagicMock())
sys.modules.setdefault("twilio.rest", _mock_twilio_rest)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import TenantConfig, LeadCriteria
from tools.email_tool import OutboundMessage
from tools.whatsapp_tool import (
    _validate_phone,
    _whatsapp_addr,
    send_whatsapp_summary,
    is_whatsapp_read,
    _send_with_retry,
    _MAX_RETRIES,
    _RETRY_BASE_SECONDS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_tenant(**kwargs) -> TenantConfig:
    defaults = dict(
        tenant_id="tenant_001",
        company_name="Growth Bizon",
        language="en",
        geo_center="Houston, TX",
        lead_criteria=LeadCriteria(),
        sender_name="Sales Team",
        sender_email="sales@growthbizon.com",
        owner_whatsapp="+15551234567",
        owner_name="Carlos",
        rag_collection="rag_tenant_001",
    )
    defaults.update(kwargs)
    return TenantConfig(**defaults)


@pytest.fixture(autouse=True)
def reset_twilio_mock():
    """Reset all Twilio mock state (including side_effect) between tests."""
    _mock_twilio_rest.reset_mock(side_effect=True)
    _mock_client.reset_mock(side_effect=True)
    yield


# ---------------------------------------------------------------------------
# _validate_phone — E.164 validation
# ---------------------------------------------------------------------------

class TestValidatePhone:
    def test_valid_us_number(self):
        assert _validate_phone("+15551234567") is True

    def test_valid_mexican_number(self):
        assert _validate_phone("+525512345678") is True

    def test_valid_international_long(self):
        assert _validate_phone("+441234567890") is True

    def test_invalid_no_plus(self):
        assert _validate_phone("15551234567") is False

    def test_invalid_starts_with_plus_zero(self):
        # E.164 requires first digit after + to be 1-9
        assert _validate_phone("+05551234567") is False

    def test_invalid_too_short(self):
        assert _validate_phone("+123456789") is False

    def test_invalid_too_long(self):
        assert _validate_phone("+1234567890123456") is False

    def test_invalid_contains_letters(self):
        assert _validate_phone("+1555ABC4567") is False

    def test_invalid_empty_string(self):
        assert _validate_phone("") is False

    def test_invalid_whitespace_only(self):
        assert _validate_phone("   ") is False

    def test_strips_whitespace_before_validating(self):
        assert _validate_phone("  +15551234567  ") is True

    def test_invalid_dashes_included(self):
        assert _validate_phone("+1-555-123-4567") is False


# ---------------------------------------------------------------------------
# _whatsapp_addr — scheme prefix
# ---------------------------------------------------------------------------

class TestWhatsappAddr:
    def test_adds_whatsapp_prefix(self):
        assert _whatsapp_addr("+15551234567") == "whatsapp:+15551234567"

    def test_preserves_existing_number_exactly(self):
        result = _whatsapp_addr("+525512345678")
        assert result.startswith("whatsapp:")
        assert "+525512345678" in result


# ---------------------------------------------------------------------------
# send_whatsapp_summary — dry-run path
# ---------------------------------------------------------------------------

class TestSendWhatsappSummaryDryRun:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_dry_run_returns_outbound_message(self):
        result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        assert isinstance(result, OutboundMessage)

    def test_dry_run_status_is_dry_run(self):
        result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        assert result.status == "dry_run"

    def test_dry_run_flag_is_true(self):
        result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        assert result.dry_run is True

    def test_dry_run_channel_is_whatsapp(self):
        result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        assert result.channel == "whatsapp"

    def test_dry_run_sent_at_is_none(self):
        result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        assert result.sent_at is None

    def test_dry_run_message_id_is_none(self):
        result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        assert result.message_id is None

    def test_dry_run_subject_is_none(self):
        result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        assert result.subject is None

    def test_dry_run_body_set(self):
        result = send_whatsapp_summary(self.tenant, "Daily summary here", dry_run=True)
        assert result.body == "Daily summary here"

    def test_dry_run_recipient_is_owner_whatsapp(self):
        result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        assert result.recipient == "+15551234567"

    def test_dry_run_tenant_id_set(self):
        result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        assert result.tenant_id == "tenant_001"

    def test_dry_run_never_calls_twilio(self):
        send_whatsapp_summary(self.tenant, "Summary text", dry_run=True)
        _mock_client.messages.create.assert_not_called()

    def test_dry_run_via_settings_fallback(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = True
            result = send_whatsapp_summary(self.tenant, "Summary text", dry_run=None)
        assert result.status == "dry_run"


# ---------------------------------------------------------------------------
# send_whatsapp_summary — phone validation
# ---------------------------------------------------------------------------

class TestSendWhatsappSummaryValidation:
    def test_missing_phone_raises_value_error(self):
        tenant = _make_tenant(owner_whatsapp="")
        with pytest.raises(ValueError, match="Invalid or missing owner_whatsapp"):
            send_whatsapp_summary(tenant, "Summary", dry_run=True)

    def test_invalid_phone_format_raises_value_error(self):
        tenant = _make_tenant(owner_whatsapp="not-a-phone")
        with pytest.raises(ValueError):
            send_whatsapp_summary(tenant, "Summary", dry_run=True)

    def test_validation_runs_before_dry_run_check(self):
        """ValueError should raise even in dry-run mode."""
        tenant = _make_tenant(owner_whatsapp="bad")
        with pytest.raises(ValueError):
            send_whatsapp_summary(tenant, "Summary", dry_run=True)

    def test_non_e164_raises_value_error(self):
        tenant = _make_tenant(owner_whatsapp="5551234567")
        with pytest.raises(ValueError):
            send_whatsapp_summary(tenant, "Summary", dry_run=True)


# ---------------------------------------------------------------------------
# send_whatsapp_summary — production success
# ---------------------------------------------------------------------------

class TestSendWhatsappSummaryProductionSuccess:
    def setup_method(self):
        self.tenant = _make_tenant()
        _mock_client.messages.create.return_value.sid = "SMabc123"

    def test_returns_outbound_message(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert isinstance(result, OutboundMessage)

    def test_status_is_sent(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert result.status == "sent"

    def test_channel_is_whatsapp(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert result.channel == "whatsapp"

    def test_dry_run_flag_is_false(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert result.dry_run is False

    def test_message_id_is_twilio_sid(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert result.message_id == "SMabc123"

    def test_sent_at_is_datetime(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert isinstance(result.sent_at, datetime)

    def test_to_address_uses_whatsapp_scheme(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        call_kwargs = _mock_client.messages.create.call_args[1]
        assert call_kwargs["to"] == "whatsapp:+15551234567"

    def test_from_address_uses_whatsapp_scheme(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            send_whatsapp_summary(self.tenant, "Summary text", dry_run=False)
        call_kwargs = _mock_client.messages.create.call_args[1]
        assert call_kwargs["from_"] == "whatsapp:+14155238886"

    def test_body_passed_to_twilio(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            send_whatsapp_summary(self.tenant, "The daily summary", dry_run=False)
        call_kwargs = _mock_client.messages.create.call_args[1]
        assert call_kwargs["body"] == "The daily summary"

    def test_twilio_called_once(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        _mock_client.messages.create.assert_called_once()


# ---------------------------------------------------------------------------
# send_whatsapp_summary — production failure
# ---------------------------------------------------------------------------

class TestSendWhatsappSummaryProductionFailure:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_api_failure_returns_failed_status(self):
        _mock_client.messages.create.side_effect = Exception("Twilio timeout")
        with patch("tools.whatsapp_tool.settings") as ms, \
             patch("tools.whatsapp_tool.time.sleep"):
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert result.status == "failed"

    def test_api_failure_sent_at_is_none(self):
        _mock_client.messages.create.side_effect = Exception("err")
        with patch("tools.whatsapp_tool.settings") as ms, \
             patch("tools.whatsapp_tool.time.sleep"):
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert result.sent_at is None

    def test_api_failure_message_id_is_none(self):
        _mock_client.messages.create.side_effect = Exception("err")
        with patch("tools.whatsapp_tool.settings") as ms, \
             patch("tools.whatsapp_tool.time.sleep"):
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert result.message_id is None

    def test_api_failure_does_not_raise(self):
        _mock_client.messages.create.side_effect = Exception("network error")
        with patch("tools.whatsapp_tool.settings") as ms, \
             patch("tools.whatsapp_tool.time.sleep"):
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert result is not None

    def test_api_failure_dry_run_is_false(self):
        _mock_client.messages.create.side_effect = Exception("err")
        with patch("tools.whatsapp_tool.settings") as ms, \
             patch("tools.whatsapp_tool.time.sleep"):
            ms.dry_run = False
            ms.twilio_account_sid = "ACtest"
            ms.twilio_auth_token = "authtoken"
            ms.twilio_whatsapp_number = "+14155238886"
            result = send_whatsapp_summary(self.tenant, "Summary", dry_run=False)
        assert result.dry_run is False


# ---------------------------------------------------------------------------
# is_whatsapp_read — dry-run path
# ---------------------------------------------------------------------------

class TestIsWhatsappReadDryRun:
    def test_dry_run_returns_false(self):
        assert is_whatsapp_read("SMabc123", dry_run=True) is False

    def test_dry_run_never_calls_twilio(self):
        is_whatsapp_read("SMabc123", dry_run=True)
        _mock_client.messages.assert_not_called()

    def test_dry_run_via_settings_fallback(self):
        with patch("tools.whatsapp_tool.settings") as ms:
            ms.dry_run = True
            result = is_whatsapp_read("SMabc123", dry_run=None)
        assert result is False

    def test_dry_run_with_empty_sid_still_returns_false(self):
        assert is_whatsapp_read("", dry_run=True) is False


# ---------------------------------------------------------------------------
# is_whatsapp_read — production path
# ---------------------------------------------------------------------------

class TestIsWhatsappReadProduction:
    def _patch_settings(self):
        ms = MagicMock()
        ms.dry_run = False
        ms.twilio_account_sid = "ACtest"
        ms.twilio_auth_token = "authtoken"
        return ms

    def test_returns_true_when_status_is_read(self):
        _mock_client.messages.return_value.fetch.return_value.status = "read"
        with patch("tools.whatsapp_tool.settings", self._patch_settings()):
            result = is_whatsapp_read("SMabc123", dry_run=False)
        assert result is True

    def test_returns_false_when_status_is_delivered(self):
        _mock_client.messages.return_value.fetch.return_value.status = "delivered"
        with patch("tools.whatsapp_tool.settings", self._patch_settings()):
            result = is_whatsapp_read("SMabc123", dry_run=False)
        assert result is False

    def test_returns_false_when_status_is_sent(self):
        _mock_client.messages.return_value.fetch.return_value.status = "sent"
        with patch("tools.whatsapp_tool.settings", self._patch_settings()):
            result = is_whatsapp_read("SMabc123", dry_run=False)
        assert result is False

    def test_returns_false_when_status_is_failed(self):
        _mock_client.messages.return_value.fetch.return_value.status = "failed"
        with patch("tools.whatsapp_tool.settings", self._patch_settings()):
            result = is_whatsapp_read("SMabc123", dry_run=False)
        assert result is False

    def test_returns_false_on_twilio_exception(self):
        _mock_client.messages.return_value.fetch.side_effect = Exception("API error")
        with patch("tools.whatsapp_tool.settings", self._patch_settings()):
            result = is_whatsapp_read("SMabc123", dry_run=False)
        assert result is False

    def test_does_not_raise_on_twilio_exception(self):
        _mock_client.messages.return_value.fetch.side_effect = Exception("timeout")
        with patch("tools.whatsapp_tool.settings", self._patch_settings()):
            result = is_whatsapp_read("SMabc123", dry_run=False)
        assert result is not None

    def test_empty_sid_returns_false_without_twilio_call(self):
        with patch("tools.whatsapp_tool.settings", self._patch_settings()):
            result = is_whatsapp_read("", dry_run=False)
        assert result is False
        _mock_client.messages.assert_not_called()

    def test_fetches_by_correct_sid(self):
        _mock_client.messages.return_value.fetch.return_value.status = "read"
        with patch("tools.whatsapp_tool.settings", self._patch_settings()):
            is_whatsapp_read("SMxyz999", dry_run=False)
        _mock_client.messages.assert_called_with("SMxyz999")


# ---------------------------------------------------------------------------
# _send_with_retry — backoff behaviour
# ---------------------------------------------------------------------------

class TestSendWithRetry:
    def test_success_on_first_attempt_returns_sid(self):
        _mock_client.messages.create.return_value.sid = "SMfirst"
        result = _send_with_retry("f", "t", "body", "AC", "auth")
        assert result == "SMfirst"

    def test_success_on_first_attempt_calls_create_once(self):
        _mock_client.messages.create.return_value.sid = "SMfirst"
        _send_with_retry("f", "t", "body", "AC", "auth")
        assert _mock_client.messages.create.call_count == 1

    def test_retry_on_failure_then_success(self):
        _mock_client.messages.create.side_effect = [
            Exception("fail 1"),
            MagicMock(sid="SMretry"),
        ]
        with patch("tools.whatsapp_tool.time.sleep"):
            result = _send_with_retry("f", "t", "body", "AC", "auth")
        assert result == "SMretry"

    def test_all_retries_exhausted_raises(self):
        _mock_client.messages.create.side_effect = Exception("always fails")
        with patch("tools.whatsapp_tool.time.sleep"), \
             pytest.raises(Exception, match="always fails"):
            _send_with_retry("f", "t", "body", "AC", "auth")

    def test_total_attempts_equals_max_retries_plus_one(self):
        _mock_client.messages.create.side_effect = Exception("fail")
        with patch("tools.whatsapp_tool.time.sleep"):
            try:
                _send_with_retry("f", "t", "body", "AC", "auth")
            except Exception:
                pass
        assert _mock_client.messages.create.call_count == _MAX_RETRIES + 1

    def test_backoff_delays_are_exponential(self):
        _mock_client.messages.create.side_effect = Exception("fail")
        sleep_calls = []
        with patch("tools.whatsapp_tool.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            try:
                _send_with_retry("f", "t", "body", "AC", "auth")
            except Exception:
                pass
        assert sleep_calls[0] == pytest.approx(_RETRY_BASE_SECONDS * 1)
        assert sleep_calls[1] == pytest.approx(_RETRY_BASE_SECONDS * 2)
        assert sleep_calls[2] == pytest.approx(_RETRY_BASE_SECONDS * 4)

    def test_no_sleep_after_last_attempt(self):
        _mock_client.messages.create.side_effect = Exception("fail")
        sleep_calls = []
        with patch("tools.whatsapp_tool.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            try:
                _send_with_retry("f", "t", "body", "AC", "auth")
            except Exception:
                pass
        assert len(sleep_calls) == _MAX_RETRIES

    def test_client_initialized_with_credentials(self):
        _mock_client.messages.create.return_value.sid = "SMx"
        _send_with_retry("f", "t", "body", "ACfoo", "bar_token")
        _mock_twilio_rest.Client.assert_called_with("ACfoo", "bar_token")

    def test_missing_sid_in_response_returns_empty_string(self):
        _mock_client.messages.create.return_value.sid = None
        result = _send_with_retry("f", "t", "body", "AC", "auth")
        assert result == ""
