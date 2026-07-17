"""
Twilio WhatsApp wrapper for end-of-day owner summaries.

Owns the whatsapp channel of Contract 5 — OutboundMessage (TEAM.md).
Consumed by director.py (end_of_day_sequence).

Guarantees:
  - DRY_RUN gate checked before ANY Twilio call. In dry-run, logs the full
    message body and returns OutboundMessage(status="dry_run").
  - E.164 phone validation before dry-run or real send attempt (fail fast).
  - Exponential backoff on API failures: up to _MAX_RETRIES retries,
    delays 1 s → 2 s → 4 s between attempts.
  - twilio is lazy-imported so the module loads fast in test / dry-run contexts.
  - is_whatsapp_read() returns False on any error so director safely escalates
    to voice call rather than silently dropping the alert.

Public API:
    send_whatsapp_summary(tenant_config, summary_text, dry_run=None) -> OutboundMessage
    is_whatsapp_read(message_sid, dry_run=None) -> bool
"""

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


def _get_logger(tenant_id: str) -> logging.Logger:
    log_dir = _LOGS_ROOT / tenant_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.log"

    logger = logging.getLogger(f"whatsapp_tool.{tenant_id}")
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
# Internal helpers
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 1.0


def _whatsapp_addr(phone: str) -> str:
    """Prefix a bare E.164 number with the 'whatsapp:' scheme Twilio requires."""
    return f"whatsapp:{phone}"


def _send_with_retry(
    from_addr: str,
    to_addr: str,
    body: str,
    account_sid: str,
    auth_token: str,
) -> str:
    """
    Call Twilio Messages API with exponential backoff.

    Attempts: up to _MAX_RETRIES + 1 total (1 initial + 3 retries).
    Backoff delays between attempts: 1 s, 2 s, 4 s.

    Returns:
        Twilio message SID string on success.

    Raises:
        The last exception raised by Twilio if all attempts fail.
    """
    from twilio.rest import Client  # lazy import

    client = Client(account_sid, auth_token)

    last_exc: Exception = RuntimeError("send never attempted")
    for attempt in range(_MAX_RETRIES + 1):
        try:
            message = client.messages.create(
                from_=from_addr,
                to=to_addr,
                body=body,
            )
            return message.sid or ""
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_SECONDS * (2 ** attempt)
                time.sleep(delay)

    raise last_exc


def _fetch_message_status(
    message_sid: str,
    account_sid: str,
    auth_token: str,
) -> str:
    """Fetch a Twilio message and return its status string."""
    from twilio.rest import Client  # lazy import

    client = Client(account_sid, auth_token)
    message = client.messages(message_sid).fetch()
    return message.status or ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_whatsapp_summary(
    tenant_config: TenantConfig,
    summary_text: str,
    dry_run: Optional[bool] = None,
) -> OutboundMessage:
    """
    Send the daily report summary to the tenant owner via WhatsApp.

    Args:
        tenant_config:  Provides owner_whatsapp recipient and tenant identity.
        summary_text:   Plain-text message body (typically DailyReport.summary_text).
        dry_run:        True  → log + return dry_run OutboundMessage, no Twilio call.
                        None  → falls back to settings.dry_run.

    Returns:
        OutboundMessage with channel="whatsapp" and status "sent", "failed",
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

    # ------------------------------------------------------------------
    # DRY-RUN — log full message, never call Twilio
    # ------------------------------------------------------------------
    if is_dry_run:
        logger.info(
            "[DRY_RUN] WhatsApp summary would be sent | tenant=%s | to=%s",
            tenant_config.tenant_id, _mask_phone(recipient),
        )
        logger.info("[DRY_RUN] BODY:\n%s", summary_text)

        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id="director",
            channel="whatsapp",
            recipient=recipient,
            subject=None,
            body=summary_text,
            sent_at=None,
            status="dry_run",
            dry_run=True,
            message_id=None,
        )

    # ------------------------------------------------------------------
    # PRODUCTION — call Twilio with exponential backoff
    # ------------------------------------------------------------------
    from_addr = _whatsapp_addr(settings.twilio_whatsapp_number)
    to_addr = _whatsapp_addr(recipient)

    logger.info(
        "Sending WhatsApp summary | tenant=%s | to=%s",
        tenant_config.tenant_id, _mask_phone(recipient),
    )

    try:
        message_sid = _send_with_retry(
            from_addr=from_addr,
            to_addr=to_addr,
            body=summary_text,
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
        )
        sent_at = datetime.utcnow()
        logger.info(
            "WhatsApp sent | tenant=%s | sid=%s",
            tenant_config.tenant_id, message_sid,
        )
        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id="director",
            channel="whatsapp",
            recipient=recipient,
            subject=None,
            body=summary_text,
            sent_at=sent_at,
            status="sent",
            dry_run=False,
            message_id=message_sid,
        )

    except Exception as exc:
        logger.error(
            "WhatsApp failed after %d retries | tenant=%s | error=%s",
            _MAX_RETRIES, tenant_config.tenant_id, exc,
        )
        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id="director",
            channel="whatsapp",
            recipient=recipient,
            subject=None,
            body=summary_text,
            sent_at=None,
            status="failed",
            dry_run=False,
            message_id=None,
        )


def is_whatsapp_read(
    message_sid: str,
    dry_run: Optional[bool] = None,
) -> bool:
    """
    Check whether the owner has read a sent WhatsApp message.

    Queries the Twilio Messages API for the current status of the message.
    Returns True only when Twilio reports status == "read" (requires WhatsApp
    Business read receipts to be enabled on the Twilio number).

    Args:
        message_sid:  Twilio SID from OutboundMessage.message_id.
        dry_run:      True  → log and return False. Returning False is the safe
                               default — it lets director exercise the full voice-
                               escalation path without making a real Twilio call.
                      None  → falls back to settings.dry_run.

    Returns:
        True if Twilio reports status == "read".
        False in all other cases: undelivered, delivered-but-not-read, failed,
        dry-run, empty/None sid, or any Twilio API error.
    """
    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run

    if is_dry_run:
        logging.getLogger("whatsapp_tool").info(
            "[DRY_RUN] is_whatsapp_read | sid=%s | returning False", message_sid,
        )
        return False

    if not message_sid:
        return False

    try:
        status = _fetch_message_status(
            message_sid=message_sid,
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
        )
        return status == "read"
    except Exception:
        # Twilio lookup failure → assume not read so director escalates to voice
        return False
