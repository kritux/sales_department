"""
Twilio outbound voice call + ElevenLabs TTS for urgent owner alerts.

Owns the voice channel of Contract 5 — OutboundMessage (TEAM.md).
Consumed by director.py (end_of_day_sequence) when WhatsApp goes unread.

Pipeline (production):
  1. _build_script()        — craft spoken script under 30 sec (~65 words)
  2. _synthesize_audio()    — ElevenLabs TTS → MP3 bytes
  3. _save_audio()          — write bytes to logs/{tenant_id}/calls/TIMESTAMP.mp3
  4. _build_twiml_*()       — inline Twilio XML
       If settings.audio_base_url set → <Play url="…/calls/audio/FILE"/>
       Otherwise             → <Say voice="alice">SCRIPT</Say> fallback
  5. _call_with_retry()     — Twilio outbound call, exponential backoff

The <Say> fallback keeps the tool fully functional in local dev where the
FastAPI server is not yet publicly reachable. Set AUDIO_BASE_URL in prod
(Railway public URL) to serve the ElevenLabs audio via the <Play> verb.

Guarantees:
  - DRY_RUN gate checked before ElevenLabs or Twilio. Logs script + returns
    OutboundMessage(status="dry_run") without any external calls.
  - E.164 phone validation before dry-run or real call (fail fast).
  - Exponential backoff on Twilio failures: up to _MAX_RETRIES retries,
    delays 1 s → 2 s → 4 s between attempts.
  - ElevenLabs and twilio are lazy-imported (module loads fast in tests).
  - Any ElevenLabs failure returns OutboundMessage(status="failed") — never raises.

Public API:
    alert_owner_by_voice(tenant_config, message, dry_run=None) -> OutboundMessage
"""

import html
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from config.settings import settings
from config.tenants import TenantConfig
from tools.email_tool import OutboundMessage

# ---------------------------------------------------------------------------
# Paths / logging
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOGS_ROOT = _REPO_ROOT / "logs"

# Words per minute for average spoken English; 130 wpm → ~65 words = ~30 sec
_WORDS_PER_MINUTE = 130
_MAX_SCRIPT_WORDS = 65   # ≈ 30 seconds at _WORDS_PER_MINUTE


def _get_logger(tenant_id: str) -> logging.Logger:
    log_dir = _LOGS_ROOT / tenant_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.log"

    logger = logging.getLogger(f"call_tool.{tenant_id}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Phone validation (E.164)
# ---------------------------------------------------------------------------

_E164_RE = re.compile(r"^\+[1-9]\d{9,14}$")


def _validate_phone(number: str) -> bool:
    """Return True when number is a valid E.164 string, False otherwise."""
    if not number or not number.strip():
        return False
    return bool(_E164_RE.match(number.strip()))


def _mask_phone(number: str) -> str:
    """Return last-4-visible mask of a phone number for safe logging."""
    digits = number.lstrip("+")
    return f"+***{digits[-4:]}" if len(digits) >= 4 else "***"


# ---------------------------------------------------------------------------
# Script builder
# ---------------------------------------------------------------------------

def _build_script(owner_name: str, message: str) -> str:
    """
    Build a spoken alert script that fits under 30 seconds (~65 words at 130 wpm).

    Structure: greeting → truncated message → CTA to check WhatsApp.

    Args:
        owner_name: TenantConfig.owner_name — first word is used as greeting.
        message:    Urgent alert text from the Director.
    """
    first_name = owner_name.split()[0] if owner_name.strip() else "there"

    greeting = f"Hi {first_name}, this is your sales AI with an urgent update."
    cta = "Please check your WhatsApp for full details. Thank you."

    # Reserve words for greeting and CTA, truncate message to fill the rest
    reserved = len(greeting.split()) + len(cta.split())
    budget = max(0, _MAX_SCRIPT_WORDS - reserved)

    words = message.split()
    if len(words) > budget:
        short_message = " ".join(words[:budget]) + "."
    else:
        short_message = message.strip().rstrip(".") + "."

    return f"{greeting} {short_message} {cta}"


# ---------------------------------------------------------------------------
# ElevenLabs synthesis
# ---------------------------------------------------------------------------

def _synthesize_audio(script: str, api_key: str, voice_id: str) -> bytes:
    """
    Synthesize speech via ElevenLabs and return MP3 bytes.

    Uses eleven_monolingual_v1 model. Raises on API error — caller handles.

    Args:
        script:   Text to synthesize.
        api_key:  ElevenLabs API key.
        voice_id: ElevenLabs voice ID (default: Rachel "21m00Tcm4TlvDq8ikWAM").
    """
    from elevenlabs.client import ElevenLabs  # lazy import

    client = ElevenLabs(api_key=api_key)
    audio = client.generate(
        text=script,
        voice=voice_id,
        model="eleven_monolingual_v1",
    )
    return b"".join(audio)


def _save_audio(audio_bytes: bytes, tenant_id: str) -> Path:
    """
    Write MP3 bytes to logs/{tenant_id}/calls/YYYYMMDD-HHMMSS.mp3.

    Returns the Path of the saved file.
    """
    calls_dir = _LOGS_ROOT / tenant_id / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    filename = datetime.utcnow().strftime("%Y%m%d-%H%M%S") + ".mp3"
    path = calls_dir / filename
    path.write_bytes(audio_bytes)
    return path


# ---------------------------------------------------------------------------
# TwiML builders
# ---------------------------------------------------------------------------

def _build_twiml_say(script: str) -> str:
    """
    Build TwiML that reads the script aloud using Twilio's built-in TTS.

    Used when no audio_base_url is configured (local dev / Phase 1).
    """
    escaped = html.escape(script)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say voice="alice">{escaped}</Say>'
        "</Response>"
    )


def _build_twiml_play(audio_url: str) -> str:
    """
    Build TwiML that plays a hosted MP3 file (ElevenLabs audio via FastAPI).

    Used when settings.audio_base_url is set (production on Railway).
    """
    escaped_url = html.escape(audio_url)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Play loop="1">{escaped_url}</Play>'
        "</Response>"
    )


# ---------------------------------------------------------------------------
# Twilio call with exponential backoff
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 1.0


def _call_with_retry(
    to_number: str,
    from_number: str,
    twiml: str,
    account_sid: str,
    auth_token: str,
) -> str:
    """
    Create a Twilio outbound call with exponential backoff.

    Attempts: up to _MAX_RETRIES + 1 total (1 initial + 3 retries).
    Backoff delays between attempts: 1 s, 2 s, 4 s.

    Returns:
        Twilio call SID string on success.

    Raises:
        The last exception raised by Twilio if all attempts fail.
    """
    from twilio.rest import Client  # lazy import

    client = Client(account_sid, auth_token)

    last_exc: Exception = RuntimeError("call never attempted")
    for attempt in range(_MAX_RETRIES + 1):
        try:
            call = client.calls.create(
                to=to_number,
                from_=from_number,
                twiml=twiml,
            )
            return call.sid or ""
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_SECONDS * (2 ** attempt)
                time.sleep(delay)

    raise last_exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def alert_owner_by_voice(
    tenant_config: TenantConfig,
    message: str,
    dry_run: Optional[bool] = None,
) -> OutboundMessage:
    """
    Synthesize an urgent spoken alert with ElevenLabs and call the owner via Twilio.

    Args:
        tenant_config:  Provides owner_whatsapp (used as call destination) and
                        owner_name (used in script greeting).
        message:        Urgent alert text — truncated to fit ~30 seconds if needed.
        dry_run:        True  → log script + return dry_run OutboundMessage, no calls.
                        None  → falls back to settings.dry_run.

    Returns:
        OutboundMessage with channel="voice" and status "sent", "failed",
        or "dry_run".

    Raises:
        ValueError: if owner_whatsapp is missing or not a valid E.164 number.
    """
    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run
    logger = _get_logger(tenant_config.tenant_id)

    recipient = tenant_config.owner_whatsapp or ""

    if not _validate_phone(recipient):
        raise ValueError(
            f"Invalid or missing owner_whatsapp for tenant "
            f"{tenant_config.tenant_id!r}: {recipient!r}"
        )

    script = _build_script(tenant_config.owner_name, message)

    # ------------------------------------------------------------------
    # DRY-RUN — log script, no ElevenLabs or Twilio calls
    # ------------------------------------------------------------------
    if is_dry_run:
        logger.info(
            "[DRY_RUN] Voice alert would be sent | tenant=%s | to=%s",
            tenant_config.tenant_id, _mask_phone(recipient),
        )
        logger.info("[DRY_RUN] SCRIPT:\n%s", script)

        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id="director",
            channel="voice",
            recipient=recipient,
            subject=None,
            body=script,
            sent_at=None,
            status="dry_run",
            dry_run=True,
            message_id=None,
        )

    # ------------------------------------------------------------------
    # PRODUCTION — synthesize → save → call
    # ------------------------------------------------------------------
    logger.info(
        "Voice alert | tenant=%s | to=%s | script_words=%d",
        tenant_config.tenant_id, _mask_phone(recipient), len(script.split()),
    )

    try:
        audio_bytes = _synthesize_audio(
            script=script,
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
        )
        audio_path = _save_audio(audio_bytes, tenant_config.tenant_id)
        logger.info(
            "ElevenLabs audio saved | tenant=%s | path=%s | size=%d bytes",
            tenant_config.tenant_id, audio_path, len(audio_bytes),
        )
    except Exception as exc:
        logger.error(
            "ElevenLabs synthesis failed | tenant=%s | error=%s",
            tenant_config.tenant_id, exc,
        )
        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id="director",
            channel="voice",
            recipient=recipient,
            subject=None,
            body=script,
            sent_at=None,
            status="failed",
            dry_run=False,
            message_id=None,
        )

    # Build TwiML: use ElevenLabs audio URL if server is deployed, else <Say>
    if settings.audio_base_url:
        audio_url = f"{settings.audio_base_url.rstrip('/')}/calls/audio/{audio_path.name}"
        twiml = _build_twiml_play(audio_url)
        logger.info("Using <Play> TwiML | url=%s", audio_url)
    else:
        twiml = _build_twiml_say(script)
        logger.info("Using <Say> TwiML fallback (audio_base_url not set)")

    try:
        call_sid = _call_with_retry(
            to_number=recipient,
            from_number=settings.twilio_phone_number,
            twiml=twiml,
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
        )
        sent_at = datetime.utcnow()
        logger.info(
            "Voice call placed | tenant=%s | sid=%s",
            tenant_config.tenant_id, call_sid,
        )
        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id="director",
            channel="voice",
            recipient=recipient,
            subject=None,
            body=script,
            sent_at=sent_at,
            status="sent",
            dry_run=False,
            message_id=call_sid,
        )

    except Exception as exc:
        logger.error(
            "Twilio call failed after %d retries | tenant=%s | error=%s",
            _MAX_RETRIES, tenant_config.tenant_id, exc,
        )
        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id="director",
            channel="voice",
            recipient=recipient,
            subject=None,
            body=script,
            sent_at=None,
            status="failed",
            dry_run=False,
            message_id=None,
        )
