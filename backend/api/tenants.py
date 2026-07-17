"""
Tenant management endpoints.

Routes:
    GET  /tenants                — list all active tenants
    GET  /tenants/{tenant_id}   — fetch one tenant config
    POST /tenants               — create tenant (Phase 5 — Supabase required)
    PUT  /tenants/{tenant_id}   — update tenant  (Phase 5 — Supabase required)

Auth:
    All routes require Authorization: Bearer <token>.

Phase 1–4: Supabase is not wired. GET endpoints raise 503. POST/PUT raise 503.
    Phase 5 replaces stubs with real Supabase calls.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from config.tenants import TenantConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["tenants"])


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


def _load_tenant(tenant_id: str) -> TenantConfig:
    from config.tenants import load_tenant_config  # lazy
    try:
        return load_tenant_config(tenant_id)
    except NotImplementedError:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Tenant backend not yet configured. "
                f"Supabase integration is Phase 5. tenant_id={tenant_id!r}"
            ),
        )
    except Exception as exc:
        logger.error("_load_tenant | tenant=%s | error=%s", tenant_id, exc)
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")


def _list_tenants() -> List[TenantConfig]:
    from config.tenants import get_all_active_tenants  # lazy
    try:
        return get_all_active_tenants()
    except NotImplementedError:
        raise HTTPException(
            status_code=503,
            detail="Tenant listing requires Supabase integration (Phase 5).",
        )
    except Exception as exc:
        logger.error("_list_tenants | error=%s", exc)
        raise HTTPException(status_code=503, detail="Failed to list tenants")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, pattern=r"^tenant_\d{3,}$")
    company_name: str = Field(..., min_length=1)
    timezone: str = Field(default="America/Chicago")
    language: str = Field(default="en")
    geo_center: str = Field(..., min_length=1)
    sender_name: str = Field(..., min_length=1)
    sender_email: str = Field(..., min_length=1)
    owner_whatsapp: str = Field(..., min_length=1)
    owner_name: str = Field(..., min_length=1)
    rag_collection: str = Field(..., min_length=1)


class TenantUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    geo_center: Optional[str] = None
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    owner_whatsapp: Optional[str] = None
    owner_name: Optional[str] = None
    active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=List[TenantConfig])
def list_tenants(token: str = Depends(_require_auth)) -> List[TenantConfig]:
    """List all active tenants."""
    logger.info("GET /tenants")
    return _list_tenants()


@router.get("/{tenant_id}", response_model=TenantConfig)
def get_tenant(tenant_id: str, token: str = Depends(_require_auth)) -> TenantConfig:
    """Fetch config for a single tenant."""
    logger.info("GET /tenants/%s", tenant_id)
    return _load_tenant(tenant_id)


@router.post("")
def create_tenant(
    request: TenantCreateRequest,
    token: str = Depends(_require_auth),
):
    """Create a new tenant. Available in Phase 5 (Supabase required)."""
    raise HTTPException(
        status_code=503,
        detail="Tenant creation requires Supabase integration (Phase 5).",
    )


@router.put("/{tenant_id}")
def update_tenant(
    tenant_id: str,
    request: TenantUpdateRequest,
    token: str = Depends(_require_auth),
):
    """Update tenant config. Available in Phase 5 (Supabase required)."""
    raise HTTPException(
        status_code=503,
        detail=f"Tenant update requires Supabase integration (Phase 5). tenant_id={tenant_id!r}",
    )
