"""
FastAPI chat endpoint — exposes ChatAgent for web widget and inbound WhatsApp.

Routes:
    POST /chat/{tenant_id}   — single-turn chat (web widget / WhatsApp webhook)

Auth:
    All routes require Authorization: Bearer <token>.
    The token is checked for presence and format here.
    Full Supabase JWT validation is wired in Phase 5 (load_tenant_config
    will use the validated user context for RLS enforcement).

Multi-tenant isolation:
    tenant_id comes from the URL path. Every request is scoped to that tenant.
    generate_reply() receives TenantConfig — never global state.

Handoff:
    When ChatReply.handoff_triggered is True, the caller (frontend or webhook
    handler) should invoke the MeetingAgent endpoint or display a calendar
    booking link. This endpoint signals intent but does not book directly.

Error responses:
    401 — missing or malformed Authorization header
    404 — tenant not found (Supabase wired in Phase 5)
    422 — Pydantic validation failure on request body
    503 — tenant backend not yet configured (Phase 1–4 placeholder)
    500 — unexpected error in generate_reply
"""

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from config.tenants import TenantConfig
from agents.cierre.chat_agent import ChatMessage, ChatReply, generate_reply

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Opaque session identifier")
    message: str = Field(..., min_length=1, description="Prospect's latest message")
    history: List[ChatMessage] = Field(
        default_factory=list,
        description="Prior conversation turns, oldest first",
    )


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    intent: Literal["neutral", "interested", "objecting", "meeting_request"]
    buying_intent: bool
    handoff_triggered: bool
    rag_found: bool


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def _require_auth(authorization: Optional[str] = Header(None)) -> str:
    """
    Verify the Authorization header contains a Bearer token.

    Phase 5: validate token against Supabase JWT and return the user's
    tenant_id claim for RLS enforcement.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>",
        )
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty Bearer token")
    return token


# ---------------------------------------------------------------------------
# Tenant loading helper (patchable in tests)
# ---------------------------------------------------------------------------


def _load_tenant(tenant_id: str) -> TenantConfig:
    """
    Load TenantConfig for this request.

    Raises HTTPException 503 if Supabase is not yet wired (Phase 1–4).
    Raises HTTPException 404 if tenant does not exist (Phase 5+).
    """
    from config.tenants import load_tenant_config  # lazy — avoids circular at module load

    try:
        return load_tenant_config(tenant_id)
    except NotImplementedError:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Tenant backend not yet configured. "
                f"Supabase integration is scheduled for Phase 5. "
                f"tenant_id={tenant_id!r}"
            ),
        )
    except Exception as exc:
        logger.error("_load_tenant | tenant=%s | error=%s", tenant_id, exc)
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/{tenant_id}", response_model=ChatResponse)
def chat(
    tenant_id: str,
    request: ChatRequest,
    token: str = Depends(_require_auth),
) -> ChatResponse:
    """
    Single-turn chat — receive one prospect message and return one reply.

    The caller is responsible for maintaining conversation history and
    appending each exchange before the next call.

    When handoff_triggered=True in the response, the caller should surface
    a meeting-booking flow (MeetingAgent or calendar link).
    """
    logger.info(
        "POST /chat/%s | session=%s | turns=%d",
        tenant_id, request.session_id, len(request.history),
    )

    tenant_config = _load_tenant(tenant_id)

    try:
        result: ChatReply = generate_reply(
            message=request.message,
            history=request.history,
            tenant_config=tenant_config,
            session_id=request.session_id,
        )
    except Exception as exc:
        logger.error(
            "chat endpoint error | tenant=%s | session=%s | error=%s",
            tenant_id, request.session_id, exc,
        )
        raise HTTPException(status_code=500, detail="Chat agent error")

    return ChatResponse(
        session_id=result.session_id,
        reply=result.reply,
        intent=result.intent,
        buying_intent=result.buying_intent,
        handoff_triggered=result.handoff_triggered,
        rag_found=result.rag_found,
    )
