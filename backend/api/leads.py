"""
Lead management endpoints.

Routes:
    GET   /leads/{tenant_id}             — list leads (filterable by status)
    GET   /leads/{tenant_id}/{lead_id}   — fetch one lead
    PATCH /leads/{tenant_id}/{lead_id}   — update lead status or notes

Auth:
    All routes require Authorization: Bearer <token>.

Multi-tenant isolation:
    tenant_id from URL path scopes every query. No cross-tenant access.

Phase 1–4: Supabase is not wired. All endpoints return 503.
    Phase 5 replaces stubs with parameterized Supabase queries.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from db.models import Lead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["leads"])

_VALID_STATUSES = {
    "new", "contacted", "responded", "meeting_set",
    "closed_won", "closed_lost", "no_response",
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _require_auth(authorization: Optional[str] = Header(None)) -> str:
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
# Supabase stubs (patchable in tests)
# ---------------------------------------------------------------------------


def _fetch_leads(tenant_id: str, status: Optional[str], limit: int, offset: int) -> List[Lead]:
    raise HTTPException(
        status_code=503,
        detail=f"Lead listing requires Supabase integration (Phase 5). tenant_id={tenant_id!r}",
    )


def _fetch_lead(tenant_id: str, lead_id: str) -> Lead:
    raise HTTPException(
        status_code=503,
        detail=f"Lead fetch requires Supabase integration (Phase 5). tenant_id={tenant_id!r}",
    )


def _update_lead(tenant_id: str, lead_id: str, patch: "LeadPatchRequest") -> Lead:
    raise HTTPException(
        status_code=503,
        detail=f"Lead update requires Supabase integration (Phase 5). tenant_id={tenant_id!r}",
    )


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class LeadPatchRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None

    def validate_status(self) -> None:
        if self.status is not None and self.status not in _VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status {self.status!r}. Valid: {sorted(_VALID_STATUSES)}",
            )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{tenant_id}", response_model=List[Lead])
def list_leads(
    tenant_id: str,
    status: Optional[str] = Query(default=None, description="Filter by lead status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    token: str = Depends(_require_auth),
) -> List[Lead]:
    """
    List leads for a tenant.

    Optional status filter. Sorted by score descending. Paginated via
    limit/offset (max 200 per page).
    """
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status {status!r}. Valid: {sorted(_VALID_STATUSES)}",
        )
    logger.info(
        "GET /leads/%s | status=%s | limit=%d | offset=%d",
        tenant_id, status, limit, offset,
    )
    return _fetch_leads(tenant_id, status, limit, offset)


@router.get("/{tenant_id}/{lead_id}", response_model=Lead)
def get_lead(
    tenant_id: str,
    lead_id: str,
    token: str = Depends(_require_auth),
) -> Lead:
    """Fetch a single lead by ID within a tenant."""
    logger.info("GET /leads/%s/%s", tenant_id, lead_id)
    return _fetch_lead(tenant_id, lead_id)


@router.patch("/{tenant_id}/{lead_id}", response_model=Lead)
def patch_lead(
    tenant_id: str,
    lead_id: str,
    request: LeadPatchRequest,
    token: str = Depends(_require_auth),
) -> Lead:
    """Update status or notes on a lead. All fields optional."""
    request.validate_status()
    logger.info(
        "PATCH /leads/%s/%s | status=%s",
        tenant_id, lead_id, request.status,
    )
    return _update_lead(tenant_id, lead_id, request)
