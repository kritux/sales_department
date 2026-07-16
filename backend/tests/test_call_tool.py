"""
Tests for backend/tools/call_tool.py.

Both Twilio and ElevenLabs are mocked via sys.modules injection before
import, keeping the suite fully hermetic (no network, no AI packages).

ElevenLabs mock structure:
  elevenlabs.client.ElevenLabs(api_key=...)  → _mock_el_client
  _mock_el_client.generate(text, voice, model) → iterable of bytes chunks

Twilio mock structure:
  twilio.rest.Client(sid, token)  → _mock_twilio_client
  _mock_twilio_client.calls.create(to, from_, twiml) → mock with .sid

Coverage:
  - _build_script: word budget, greeting, CTA, long message truncation
  - _build_twiml_say: XML structure, HTML entity escaping, <Say> verb
  - _build_twiml_play: XML structure, <Play> verb, URL included
  - _validate_phone: E.164 regex
  - alert_owner_by_voice dry-run: no external calls, returns dry_run
  - alert_owner_by_voice phone validation: raises ValueError
  - alert_owner_by_voice production success (<Say> fallback): ElevenLabs + Twilio
  - alert_owner_by_voice production success (<Play> with URL): audio_base_url set
  - alert_owner_by_voice ElevenLabs failure: returns failed, no Twilio call
  - alert_owner_by_voice Twilio failure: returns failed, does not raise
  - _call_with_retry: backoff delays, total attempts, raises on exhaustion
"""

import sys
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Inject mocks BEFORE importing call_tool
# ---------------------------------------------------------------------------

# ElevenLabs mock
_mock_el_client = MagicMock()
_mock_el_class = MagicMock()
_mock_el_class.return_value = _mock_el_client

_mock_el_client_module = MagicMock()
_mock_el_client_module.ElevenLabs = _mock_el_class

_mock_el_module = MagicMock()
_mock_el_module.client = _mock_el_client_module

sys.modules.setdefault("elevenlabs", _mock_el_module)
sys.modules.setdefault("elevenlabs.client", _mock_el_client_module)

# Twilio mock
_mock_twilio_client = MagicMock()
_mock_twilio_rest = MagicMock()
_mock_twilio_rest.Client.return_value = _mock_twilio_client

sys.modules.setdefault("twilio", MagicMock())
sys.modules.setdefault("twilio.rest", _mock_twilio_rest)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import TenantConfig, LeadCriteria
from tools.email_tool import OutboundMessage
from tools.call_tool import (
    _build_script,
    _build_twiml_say,
    _build_twiml_play,
    _validate_phone,
    _synthesize_audio,
    _save_audio,
    _call_with_retry,
    alert_owner_by_voice,
    _MAX_RETRIES,
    _RETRY_BASE_SECONDS,
    _MAX_SCRIPT_WORDS,
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
        owner_name="Carlos Rivera",
        rag_collection="rag_tenant_001",
    )
    defaults.update(kwargs)
    return TenantConfig(**defaults)


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_el_class.reset_mock(side_effect=True)
    _mock_el_client.reset_mock(side_effect=True)
    _mock_twilio_rest.reset_mock(side_effect=True)
    _mock_twilio_client.reset_mock(side_effect=True)
    yield


# ---------------------------------------------------------------------------
# _build_script
# ---------------------------------------------------------------------------

class TestBuildScript:
    def test_returns_string(self):
        result = _build_script("Carlos", "5 new leads found today.")
        assert isinstance(result, str)

    def test_contains_first_name(self):
        result = _build_script("Carlos Rivera", "Something urgent.")
        assert "Carlos" in result

    def test_uses_only_first_word_of_name(self):
        result = _build_script("John Smith Jr", "Urgent.")
        assert "John" in result
        assert "Smith" not in result

    def test_contains_message_content(self):
        result = _build_script("Carlos", "Pipeline value exceeded 5000 dollars.")
        assert "Pipeline" in result or "pipeline" in result.lower()

    def test_contains_whatsapp_cta(self):
        result = _build_script("Carlos", "Urgent news.")
        assert "WhatsApp" in result

    def test_word_count_within_budget(self):
        long_message = " ".join(["word"] * 200)
        result = _build_script("Carlos", long_message)
        assert len(result.split()) <= _MAX_SCRIPT_WORDS + 5  # small tolerance

    def test_short_message_not_truncated(self):
        short = "5 new leads found."
        result = _build_script("Carlos", short)
        assert "5 new leads found" in result

    def test_long_message_truncated(self):
        # 200-word message should be trimmed
        long_message = " ".join([f"word{i}" for i in range(200)])
        result = _build_script("Carlos", long_message)
        # Should not contain word near end
        assert "word199" not in result

    def test_empty_owner_name_uses_fallback(self):
        result = _build_script("", "Urgent message.")
        assert "there" in result

    def test_whitespace_only_name_uses_fallback(self):
        result = _build_script("   ", "Urgent message.")
        assert "there" in result

    def test_greeting_comes_first(self):
        result = _build_script("Carlos", "Urgent.")
        assert result.startswith("Hi Carlos")

    def test_cta_comes_last(self):
        result = _build_script("Carlos", "Urgent.")
        assert result.rstrip().endswith("Thank you.")


# ---------------------------------------------------------------------------
# _build_twiml_say
# ---------------------------------------------------------------------------

class TestBuildTwimlSay:
    def test_returns_string(self):
        assert isinstance(_build_twiml_say("Hello"), str)

    def test_contains_xml_declaration(self):
        result = _build_twiml_say("Hello")
        assert '<?xml version="1.0"' in result

    def test_contains_response_element(self):
        result = _build_twiml_say("Hello")
        assert "<Response>" in result and "</Response>" in result

    def test_contains_say_element(self):
        result = _build_twiml_say("Hello")
        assert "<Say" in result and "</Say>" in result

    def test_script_text_in_say(self):
        result = _build_twiml_say("Call me back please.")
        assert "Call me back please." in result

    def test_uses_alice_voice(self):
        result = _build_twiml_say("Hello")
        assert 'voice="alice"' in result

    def test_ampersand_escaped(self):
        result = _build_twiml_say("Sales & Marketing")
        assert "&amp;" in result
        assert "Sales & Marketing" not in result

    def test_less_than_escaped(self):
        result = _build_twiml_say("Score < 50")
        assert "&lt;" in result

    def test_greater_than_escaped(self):
        result = _build_twiml_say("Score > 50")
        assert "&gt;" in result

    def test_no_play_element(self):
        result = _build_twiml_say("Hello")
        assert "<Play" not in result


# ---------------------------------------------------------------------------
# _build_twiml_play
# ---------------------------------------------------------------------------

class TestBuildTwimlPlay:
    def test_returns_string(self):
        assert isinstance(_build_twiml_play("https://x.com/a.mp3"), str)

    def test_contains_play_element(self):
        result = _build_twiml_play("https://x.com/a.mp3")
        assert "<Play" in result and "</Play>" in result

    def test_url_in_play_element(self):
        result = _build_twiml_play("https://x.com/a.mp3")
        assert "https://x.com/a.mp3" in result

    def test_loop_attribute_set(self):
        result = _build_twiml_play("https://x.com/a.mp3")
        assert 'loop="1"' in result

    def test_no_say_element(self):
        result = _build_twiml_play("https://x.com/a.mp3")
        assert "<Say" not in result

    def test_contains_response_element(self):
        result = _build_twiml_play("https://x.com/a.mp3")
        assert "<Response>" in result


# ---------------------------------------------------------------------------
# _validate_phone
# ---------------------------------------------------------------------------

class TestValidatePhone:
    def test_valid_us_number(self):
        assert _validate_phone("+15551234567") is True

    def test_valid_mx_number(self):
        assert _validate_phone("+525512345678") is True

    def test_invalid_no_plus(self):
        assert _validate_phone("15551234567") is False

    def test_invalid_too_short(self):
        assert _validate_phone("+123456789") is False

    def test_invalid_empty(self):
        assert _validate_phone("") is False

    def test_strips_whitespace(self):
        assert _validate_phone("  +15551234567  ") is True

    def test_invalid_dashes(self):
        assert _validate_phone("+1-555-123-4567") is False


# ---------------------------------------------------------------------------
# alert_owner_by_voice — dry-run
# ---------------------------------------------------------------------------

class TestAlertOwnerByVoiceDryRun:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_returns_outbound_message(self):
        result = alert_owner_by_voice(self.tenant, "Urgent alert.", dry_run=True)
        assert isinstance(result, OutboundMessage)

    def test_status_is_dry_run(self):
        result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        assert result.status == "dry_run"

    def test_channel_is_voice(self):
        result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        assert result.channel == "voice"

    def test_dry_run_flag_is_true(self):
        result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        assert result.dry_run is True

    def test_sent_at_is_none(self):
        result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        assert result.sent_at is None

    def test_message_id_is_none(self):
        result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        assert result.message_id is None

    def test_subject_is_none(self):
        result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        assert result.subject is None

    def test_body_contains_script(self):
        result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        assert "Carlos" in result.body
        assert "WhatsApp" in result.body

    def test_recipient_is_owner_whatsapp(self):
        result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        assert result.recipient == "+15551234567"

    def test_tenant_id_set(self):
        result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        assert result.tenant_id == "tenant_001"

    def test_never_calls_elevenlabs(self):
        alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        _mock_el_client.generate.assert_not_called()

    def test_never_calls_twilio(self):
        alert_owner_by_voice(self.tenant, "Alert.", dry_run=True)
        _mock_twilio_client.calls.create.assert_not_called()

    def test_dry_run_via_settings_fallback(self):
        with patch("tools.call_tool.settings") as ms:
            ms.dry_run = True
            result = alert_owner_by_voice(self.tenant, "Alert.", dry_run=None)
        assert result.status == "dry_run"


# ---------------------------------------------------------------------------
# alert_owner_by_voice — phone validation
# ---------------------------------------------------------------------------

class TestAlertOwnerByVoiceValidation:
    def test_missing_phone_raises(self):
        tenant = _make_tenant(owner_whatsapp="")
        with pytest.raises(ValueError, match="Invalid or missing owner_whatsapp"):
            alert_owner_by_voice(tenant, "Alert.", dry_run=True)

    def test_invalid_phone_format_raises(self):
        tenant = _make_tenant(owner_whatsapp="not-a-phone")
        with pytest.raises(ValueError):
            alert_owner_by_voice(tenant, "Alert.", dry_run=True)

    def test_validation_runs_before_dry_run_check(self):
        tenant = _make_tenant(owner_whatsapp="bad")
        with pytest.raises(ValueError):
            alert_owner_by_voice(tenant, "Alert.", dry_run=True)


# ---------------------------------------------------------------------------
# alert_owner_by_voice — production success (<Say> fallback)
# ---------------------------------------------------------------------------

class TestAlertOwnerByVoiceProductionSayFallback:
    def setup_method(self):
        self.tenant = _make_tenant()
        _mock_el_client.generate.return_value = [b"fake", b"audio"]
        _mock_twilio_client.calls.create.return_value.sid = "CAabc123"

    def _settings(self, **kw):
        ms = MagicMock()
        ms.dry_run = False
        ms.elevenlabs_api_key = "el_key"
        ms.elevenlabs_voice_id = "voice_id"
        ms.audio_base_url = ""        # empty → <Say> fallback
        ms.twilio_account_sid = "ACtest"
        ms.twilio_auth_token = "auth"
        ms.twilio_phone_number = "+12025550000"
        for k, v in kw.items():
            setattr(ms, k, v)
        return ms

    def test_returns_outbound_message(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/20240101-120000.mp3")):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert isinstance(result, OutboundMessage)

    def test_status_is_sent(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/20240101-120000.mp3")):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.status == "sent"

    def test_channel_is_voice(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/20240101-120000.mp3")):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.channel == "voice"

    def test_dry_run_flag_is_false(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/20240101-120000.mp3")):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.dry_run is False

    def test_call_sid_in_message_id(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/20240101-120000.mp3")):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.message_id == "CAabc123"

    def test_sent_at_is_datetime(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/20240101-120000.mp3")):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert isinstance(result.sent_at, datetime)

    def test_elevenlabs_called_with_script(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/20240101-120000.mp3")):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        _mock_el_client.generate.assert_called_once()
        call_kwargs = _mock_el_client.generate.call_args[1]
        assert "Carlos" in call_kwargs.get("text", "")

    def test_say_twiml_used_when_no_audio_url(self):
        with patch("tools.call_tool.settings", self._settings(audio_base_url="")), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        create_kwargs = _mock_twilio_client.calls.create.call_args[1]
        assert "<Say" in create_kwargs["twiml"]
        assert "<Play" not in create_kwargs["twiml"]

    def test_twilio_called_with_recipient(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        create_kwargs = _mock_twilio_client.calls.create.call_args[1]
        assert create_kwargs["to"] == "+15551234567"

    def test_twilio_from_uses_settings_phone(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        create_kwargs = _mock_twilio_client.calls.create.call_args[1]
        assert create_kwargs["from_"] == "+12025550000"

    def test_audio_saved_before_call(self):
        save_called = []
        def fake_save(audio_bytes, tenant_id):
            save_called.append(True)
            return Path("/tmp/f.mp3")

        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", side_effect=fake_save):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert save_called


# ---------------------------------------------------------------------------
# alert_owner_by_voice — production success (<Play> with audio URL)
# ---------------------------------------------------------------------------

class TestAlertOwnerByVoiceProductionPlayUrl:
    def setup_method(self):
        self.tenant = _make_tenant()
        _mock_el_client.generate.return_value = [b"mp3", b"data"]
        _mock_twilio_client.calls.create.return_value.sid = "CAplay123"

    def _settings(self):
        ms = MagicMock()
        ms.dry_run = False
        ms.elevenlabs_api_key = "el_key"
        ms.elevenlabs_voice_id = "voice_id"
        ms.audio_base_url = "https://app.railway.app"
        ms.twilio_account_sid = "ACtest"
        ms.twilio_auth_token = "auth"
        ms.twilio_phone_number = "+12025550000"
        return ms

    def test_play_twiml_used_when_audio_url_set(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/20240101-120000.mp3")):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        create_kwargs = _mock_twilio_client.calls.create.call_args[1]
        assert "<Play" in create_kwargs["twiml"]
        assert "<Say" not in create_kwargs["twiml"]

    def test_play_twiml_contains_audio_filename(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/20240101-120000.mp3")):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        create_kwargs = _mock_twilio_client.calls.create.call_args[1]
        assert "20240101-120000.mp3" in create_kwargs["twiml"]

    def test_play_twiml_contains_base_url(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        create_kwargs = _mock_twilio_client.calls.create.call_args[1]
        assert "app.railway.app" in create_kwargs["twiml"]

    def test_trailing_slash_in_base_url_not_doubled(self):
        ms = self._settings()
        ms.audio_base_url = "https://app.railway.app/"
        with patch("tools.call_tool.settings", ms), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        create_kwargs = _mock_twilio_client.calls.create.call_args[1]
        assert "//calls" not in create_kwargs["twiml"]


# ---------------------------------------------------------------------------
# alert_owner_by_voice — ElevenLabs failure
# ---------------------------------------------------------------------------

class TestAlertOwnerByVoiceElevenLabsFailure:
    def setup_method(self):
        self.tenant = _make_tenant()
        _mock_el_client.generate.side_effect = Exception("ElevenLabs timeout")

    def _settings(self):
        ms = MagicMock()
        ms.dry_run = False
        ms.elevenlabs_api_key = "el_key"
        ms.elevenlabs_voice_id = "voice_id"
        ms.audio_base_url = ""
        ms.twilio_account_sid = "ACtest"
        ms.twilio_auth_token = "auth"
        ms.twilio_phone_number = "+12025550000"
        return ms

    def test_returns_failed_status(self):
        with patch("tools.call_tool.settings", self._settings()):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.status == "failed"

    def test_does_not_raise(self):
        with patch("tools.call_tool.settings", self._settings()):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result is not None

    def test_twilio_never_called_when_elevenlabs_fails(self):
        with patch("tools.call_tool.settings", self._settings()):
            alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        _mock_twilio_client.calls.create.assert_not_called()

    def test_sent_at_is_none(self):
        with patch("tools.call_tool.settings", self._settings()):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.sent_at is None

    def test_message_id_is_none(self):
        with patch("tools.call_tool.settings", self._settings()):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.message_id is None


# ---------------------------------------------------------------------------
# alert_owner_by_voice — Twilio failure
# ---------------------------------------------------------------------------

class TestAlertOwnerByVoiceTwilioFailure:
    def setup_method(self):
        self.tenant = _make_tenant()
        _mock_el_client.generate.return_value = [b"audio"]
        _mock_twilio_client.calls.create.side_effect = Exception("Twilio error")

    def _settings(self):
        ms = MagicMock()
        ms.dry_run = False
        ms.elevenlabs_api_key = "el_key"
        ms.elevenlabs_voice_id = "voice_id"
        ms.audio_base_url = ""
        ms.twilio_account_sid = "ACtest"
        ms.twilio_auth_token = "auth"
        ms.twilio_phone_number = "+12025550000"
        return ms

    def test_returns_failed_status(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")), \
             patch("tools.call_tool.time.sleep"):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.status == "failed"

    def test_does_not_raise(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")), \
             patch("tools.call_tool.time.sleep"):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result is not None

    def test_sent_at_is_none(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")), \
             patch("tools.call_tool.time.sleep"):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.sent_at is None

    def test_message_id_is_none(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")), \
             patch("tools.call_tool.time.sleep"):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.message_id is None

    def test_dry_run_is_false(self):
        with patch("tools.call_tool.settings", self._settings()), \
             patch("tools.call_tool._save_audio", return_value=Path("/tmp/f.mp3")), \
             patch("tools.call_tool.time.sleep"):
            result = alert_owner_by_voice(self.tenant, "Urgent.", dry_run=False)
        assert result.dry_run is False


# ---------------------------------------------------------------------------
# _call_with_retry — backoff behaviour
# ---------------------------------------------------------------------------

class TestCallWithRetry:
    def test_success_on_first_attempt_returns_sid(self):
        _mock_twilio_client.calls.create.return_value.sid = "CA001"
        result = _call_with_retry("+1555", "+1444", "<Response/>", "AC", "auth")
        assert result == "CA001"

    def test_calls_create_called_once_on_success(self):
        _mock_twilio_client.calls.create.return_value.sid = "CA001"
        _call_with_retry("+1555", "+1444", "<Response/>", "AC", "auth")
        assert _mock_twilio_client.calls.create.call_count == 1

    def test_retry_on_failure_then_success(self):
        _mock_twilio_client.calls.create.side_effect = [
            Exception("fail 1"),
            MagicMock(sid="CAretry"),
        ]
        with patch("tools.call_tool.time.sleep"):
            result = _call_with_retry("+1555", "+1444", "<Response/>", "AC", "auth")
        assert result == "CAretry"

    def test_all_retries_exhausted_raises(self):
        _mock_twilio_client.calls.create.side_effect = Exception("always fails")
        with patch("tools.call_tool.time.sleep"), \
             pytest.raises(Exception, match="always fails"):
            _call_with_retry("+1555", "+1444", "<Response/>", "AC", "auth")

    def test_total_attempts_equals_max_retries_plus_one(self):
        _mock_twilio_client.calls.create.side_effect = Exception("fail")
        with patch("tools.call_tool.time.sleep"):
            try:
                _call_with_retry("+1555", "+1444", "<Response/>", "AC", "auth")
            except Exception:
                pass
        assert _mock_twilio_client.calls.create.call_count == _MAX_RETRIES + 1

    def test_backoff_delays_are_exponential(self):
        _mock_twilio_client.calls.create.side_effect = Exception("fail")
        sleep_calls = []
        with patch("tools.call_tool.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            try:
                _call_with_retry("+1555", "+1444", "<Response/>", "AC", "auth")
            except Exception:
                pass
        assert sleep_calls[0] == pytest.approx(_RETRY_BASE_SECONDS * 1)
        assert sleep_calls[1] == pytest.approx(_RETRY_BASE_SECONDS * 2)
        assert sleep_calls[2] == pytest.approx(_RETRY_BASE_SECONDS * 4)

    def test_no_sleep_after_last_attempt(self):
        _mock_twilio_client.calls.create.side_effect = Exception("fail")
        sleep_calls = []
        with patch("tools.call_tool.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            try:
                _call_with_retry("+1555", "+1444", "<Response/>", "AC", "auth")
            except Exception:
                pass
        assert len(sleep_calls) == _MAX_RETRIES

    def test_client_initialized_with_credentials(self):
        _mock_twilio_client.calls.create.return_value.sid = "CA001"
        _call_with_retry("+1555", "+1444", "<Response/>", "ACfoo", "bar_token")
        _mock_twilio_rest.Client.assert_called_with("ACfoo", "bar_token")

    def test_missing_sid_returns_empty_string(self):
        _mock_twilio_client.calls.create.return_value.sid = None
        result = _call_with_retry("+1555", "+1444", "<Response/>", "AC", "auth")
        assert result == ""

    def test_passes_twiml_to_create(self):
        _mock_twilio_client.calls.create.return_value.sid = "CA001"
        twiml = "<Response><Say>Hi</Say></Response>"
        _call_with_retry("+1555", "+1444", twiml, "AC", "auth")
        create_kwargs = _mock_twilio_client.calls.create.call_args[1]
        assert create_kwargs["twiml"] == twiml
