"""
Tenant management endpoints.

Routes:
    GET  /tenants                — list all active tenants
    GET  /tenants/{tenant_id}   — fetch one tenant config
    POST /tenants               — create tenant (stored in tenants.json)
    PUT  /tenants/{tenant_id}   — update tenant config fields

Auth:
    All routes require Authorization: Bearer <token>.

Storage:
    Phase 1–4: tenants.json at repo root (auto-created, seeded with tenant_001).
    Phase 5: replace with Supabase calls inside config/tenants.py — no changes here.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from config.tenants import LeadCriteria, TenantConfig

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
# Storage helpers
# ---------------------------------------------------------------------------


def _load_tenant(tenant_id: str) -> TenantConfig:
    from config.tenants import load_tenant_config  # lazy
    try:
        return load_tenant_config(tenant_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id!r}")
    except Exception as exc:
        logger.error("_load_tenant | tenant=%s | error=%s", tenant_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _list_tenants() -> List[TenantConfig]:
    from config.tenants import get_all_active_tenants  # lazy
    try:
        return get_all_active_tenants()
    except Exception as exc:
        logger.error("_list_tenants | error=%s", exc)
        raise HTTPException(status_code=500, detail="Failed to list tenants")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, pattern=r"^tenant_\d{3,}$")
    company_name: str = Field(..., min_length=1)
    timezone: str = Field(default="America/Chicago")
    language: str = Field(default="en")
    geo_center: str = Field(..., min_length=1)
    geo_radius_miles: int = Field(default=50, ge=1, le=500)
    sender_name: str = Field(..., min_length=1)
    sender_email: str = Field(..., min_length=1)
    owner_whatsapp: str = Field(..., min_length=1)
    owner_name: str = Field(..., min_length=1)


class TenantUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    geo_center: Optional[str] = None
    geo_radius_miles: Optional[int] = None
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    owner_whatsapp: Optional[str] = None
    owner_name: Optional[str] = None
    active: Optional[bool] = None
    daily_contact_cap: Optional[int] = None


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


@router.post("", response_model=TenantConfig, status_code=201)
def create_tenant(
    request: TenantCreateRequest,
    token: str = Depends(_require_auth),
) -> TenantConfig:
    """Create a new tenant and persist to tenants.json."""
    from config.tenants import save_tenant_config

    # Reject duplicate
    try:
        _load_tenant(request.tenant_id)
        raise HTTPException(
            status_code=409,
            detail=f"Tenant {request.tenant_id!r} already exists",
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise

    config = TenantConfig(
        **request.model_dump(),
        lead_criteria=LeadCriteria(),
        rag_collection=f"rag_{request.tenant_id}",
    )
    save_tenant_config(config)
    logger.info("create_tenant | tenant=%s | geo=%s", config.tenant_id, config.geo_center)
    return config


@router.put("/{tenant_id}", response_model=TenantConfig)
def update_tenant(
    tenant_id: str,
    request: TenantUpdateRequest,
    token: str = Depends(_require_auth),
) -> TenantConfig:
    """Update tenant config fields. Only provided fields are changed."""
    from config.tenants import save_tenant_config

    config = _load_tenant(tenant_id)
    update_data = request.model_dump(exclude_none=True)
    updated = config.model_copy(update=update_data)
    save_tenant_config(updated)
    logger.info("update_tenant | tenant=%s | fields=%s", tenant_id, list(update_data))
    return updated
