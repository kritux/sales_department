"""
Resend API wrapper for outbound cold email.

Owns Contract 5 — OutboundMessage (TEAM.md).
Consumed by email_agent.py (Comms), director.py (Director).

Guarantees:
  - DRY_RUN gate checked before ANY Resend call. In dry-run, logs full
    rendered subject + body and returns OutboundMessage(status="dry_run").
  - Regex email validation before dry-run or real send attempt (fail fast).
  - Exponential backoff on API failures: up to _MAX_RETRIES retries,
    delays 1 s → 2 s → 4 s between attempts.
  - resend is lazy-imported so the module loads fast in test / dry-run contexts.

Public API:
    render_email(lead, tenant_config, rag_context) -> (subject, body)
    send_email(lead, tenant_config, subject, body, dry_run=None) -> OutboundMessage
"""

import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional, Tuple

from pydantic import BaseModel

from config.settings import settings
from config.tenants import TenantConfig
from db.models import Lead

# ---------------------------------------------------------------------------
# Paths / logging
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOGS_ROOT = _REPO_ROOT / "logs"


def _get_logger(tenant_id: str) -> logging.Logger:
    log_dir = _LOGS_ROOT / tenant_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.log"

    logger = logging.getLogger(f"email_tool.{tenant_id}")
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
# Contract 5 — OutboundMessage  (TEAM.md, do not change without Tech Lead sign-off)
# ---------------------------------------------------------------------------

class OutboundMessage(BaseModel):
    tenant_id: str
    lead_id: str
    channel: Literal["email", "whatsapp", "voice"] = "email"
    recipient: str                  # email address or E.164 phone
    subject: Optional[str] = None   # email only
    body: str
    sent_at: Optional[datetime] = None   # None when dry_run=True
    status: Literal["sent", "failed", "dry_run"]
    dry_run: bool
    message_id: Optional[str] = None    # Resend message ID; None in dry-run


# ---------------------------------------------------------------------------
# Email validation
# ---------------------------------------------------------------------------

# RFC 5322 simplified — practical coverage without false-negatives on valid addresses
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _validate_email(address: str) -> bool:
    """Return True when address passes regex validation, False otherwise."""
    if not address or not address.strip():
        return False
    return bool(_EMAIL_RE.match(address.strip()))


def _email_domain(address: str) -> str:
    """Return only the @domain part of an email address for safe logging."""
    at = address.find("@")
    return address[at:] if at >= 0 else "<no-domain>"


# ---------------------------------------------------------------------------
# Template renderer
# ---------------------------------------------------------------------------

def render_email(
    lead: Lead,
    tenant_config: TenantConfig,
    rag_context: str,
) -> Tuple[str, str]:
    """
    Render (subject, body) for a cold outreach email.

    Injects rag_context as the value-proposition paragraph so each email
    contains company-specific knowledge retrieved from the RAG store.

    Used by email_agent.py as a fallback template when the LLM body is
    unavailable, and always used to generate the subject line.

    Args:
        lead:           Qualified lead from filter_leads().
        tenant_config:  Sender identity and language preference.
        rag_context:    context string from RAGResponse.context — may be ""
                        when the collection has no relevant chunks.

    Returns:
        (subject, body) — both plain text. send_email() wraps body in HTML.
    """
    lang = tenant_config.language

    if lang == "es":
        subject = f"Pregunta rápida para {lead.company_name}"
        value_block = rag_context if rag_context else (
            f"En {tenant_config.company_name} ayudamos a negocios como el tuyo "
            f"a crecer con estrategias probadas para el sector de {lead.category}."
        )
        body = (
            f"Hola,\n\n"
            f"Me comunico desde {tenant_config.company_name}. Vi que "
            f"{lead.company_name} opera como {lead.category} en {lead.city} "
            f"y quería presentarme.\n\n"
            f"{value_block}\n\n"
            f"¿Tendrías 15 minutos esta semana para una llamada rápida?\n\n"
            f"Saludos,\n{tenant_config.sender_name}"
        )
    else:
        subject = f"Quick question for {lead.company_name}"
        value_block = rag_context if rag_context else (
            f"At {tenant_config.company_name} we help businesses like yours "
            f"grow with proven strategies tailored to the {lead.category} space."
        )
        body = (
            f"Hi,\n\n"
            f"I'm reaching out from {tenant_config.company_name}. I came across "
            f"{lead.company_name} and noticed you're a {lead.category} based in "
            f"{lead.city} — I wanted to introduce what we do.\n\n"
            f"{value_block}\n\n"
            f"Would you have 15 minutes this week for a quick call?\n\n"
            f"Best,\n{tenant_config.sender_name}"
        )

    return subject, body


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_html(plain: str) -> str:
    """Wrap plain-text paragraphs in minimal HTML for Resend."""
    paragraphs = plain.strip().split("\n\n")
    return "\n".join(
        f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs
    )


_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 1.0   # delay before retry 1; doubled each subsequent retry


def _send_with_retry(
    from_addr: str,
    to_addr: str,
    subject: str,
    html_body: str,
    api_key: str,
) -> str:
    """
    Call Resend API with exponential backoff.

    Attempts: up to _MAX_RETRIES + 1 total (1 initial + 3 retries).
    Backoff delays between attempts: 1 s, 2 s, 4 s.

    Returns:
        Resend message ID string on success.

    Raises:
        The last exception raised by Resend if all attempts fail.
    """
    import resend  # lazy import — keeps module fast in dry-run / tests

    resend.api_key = api_key

    last_exc: Exception = RuntimeError("send never attempted")
    for attempt in range(_MAX_RETRIES + 1):
        try:
            result = resend.Emails.send({
                "from": from_addr,
                "to": [to_addr],
                "subject": subject,
                "html": html_body,
            })
            return result.get("id") or ""
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_SECONDS * (2 ** attempt)
                time.sleep(delay)

    raise last_exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_email(
    lead: Lead,
    tenant_config: TenantConfig,
    subject: str,
    body: str,
    dry_run: Optional[bool] = None,
) -> OutboundMessage:
    """
    Send a cold email via Resend, or log it in dry-run mode.

    Args:
        lead:           Target lead. lead.email must pass regex validation.
        tenant_config:  Provides sender identity and tenant isolation.
        subject:        Email subject line.
        body:           Plain-text body (typically from render_email() or LLM).
        dry_run:        True  → log + return dry_run OutboundMessage, no API call.
                        None  → falls back to settings.dry_run.

    Returns:
        OutboundMessage with status "sent", "failed", or "dry_run".

    Raises:
        ValueError: if lead.email is missing or fails regex validation.
    """
    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run
    logger = _get_logger(tenant_config.tenant_id)

    recipient = lead.email or ""

    # Validate before doing anything else — fail fast on bad address
    if not _validate_email(recipient):
        raise ValueError(
            f"Invalid or missing email address for lead {lead.id!r}: {recipient!r}"
        )

    from_addr = f"{tenant_config.sender_name} <{tenant_config.sender_email}>"

    # ------------------------------------------------------------------
    # DRY-RUN — log full message, never call Resend
    # ------------------------------------------------------------------
    if is_dry_run:
        logger.info(
            "[DRY_RUN] Email would be sent | tenant=%s | lead=%s | to=%s",
            tenant_config.tenant_id, lead.id, _email_domain(recipient),
        )
        logger.info("[DRY_RUN] FROM:    %s", _email_domain(from_addr))
        logger.info("[DRY_RUN] TO:      %s", _email_domain(recipient))
        logger.info("[DRY_RUN] SUBJECT: %s", subject)
        logger.info("[DRY_RUN] BODY:\n%s", body)

        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id=lead.id,
            channel="email",
            recipient=recipient,
            subject=subject,
            body=body,
            sent_at=None,
            status="dry_run",
            dry_run=True,
            message_id=None,
        )

    # ------------------------------------------------------------------
    # PRODUCTION — call Resend with exponential backoff
    # ------------------------------------------------------------------
    html_body = _to_html(body)
    logger.info(
        "Sending email | tenant=%s | lead=%s | to=%s | subject=%r",
        tenant_config.tenant_id, lead.id, _email_domain(recipient), subject,
    )

    try:
        message_id = _send_with_retry(
            from_addr=from_addr,
            to_addr=recipient,
            subject=subject,
            html_body=html_body,
            api_key=settings.resend_api_key,
        )
        sent_at = datetime.utcnow()
        logger.info(
            "Email sent | tenant=%s | lead=%s | message_id=%s",
            tenant_config.tenant_id, lead.id, message_id,
        )
        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id=lead.id,
            channel="email",
            recipient=recipient,
            subject=subject,
            body=body,
            sent_at=sent_at,
            status="sent",
            dry_run=False,
            message_id=message_id,
        )

    except Exception as exc:
        logger.error(
            "Email failed after %d retries | tenant=%s | lead=%s | error=%s",
            _MAX_RETRIES, tenant_config.tenant_id, lead.id, exc,
        )
        return OutboundMessage(
            tenant_id=tenant_config.tenant_id,
            lead_id=lead.id,
            channel="email",
            recipient=recipient,
            subject=subject,
            body=body,
            sent_at=None,
            status="failed",
            dry_run=False,
            message_id=None,
        )
