"""
Contract 1 — TenantConfig (TEAM.md).
Every agent receives a TenantConfig object. Never pass raw dicts downstream.
Do not change fields without Tech Lead approval.

Phase 1–4 storage: tenants.json at repo root (auto-created on first use).
Phase 5: replace _load_all / _save_all with Supabase calls.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

AssetType = Literal[
    "logo_light",
    "logo_dark",
    "icon",
    "brand_colors_json",
    "brand_fonts_json",
]


class BrandAsset(BaseModel):
    asset_type: AssetType
    file_url: str                       # Supabase Storage path or inline JSON string
    uploaded_at: Optional[datetime] = None


class LeadCriteria(BaseModel):
    min_rating: float = 3.5
    min_reviews: int = 10
    max_reviews: Optional[int] = None
    has_website: Optional[bool] = None  # None=any, False=no site, True=has site
    company_size: Literal["any", "small", "medium", "large"] = "any"
    industries: List[str] = []
    exclude_keywords: List[str] = []


class TenantConfig(BaseModel):
    tenant_id: str
    company_name: str
    timezone: str = "America/Chicago"
    language: Literal["es", "en", "both"] = "en"
    geo_radius_miles: int = 50
    geo_center: str
    scraping_keywords: List[str] = []
    lead_criteria: LeadCriteria
    sender_name: str
    sender_email: str
    owner_whatsapp: str
    owner_name: str
    urgent_alert_threshold_usd: int = 5000
    rag_collection: str
    active: bool = True
    daily_contact_cap: int = 50         # max outbound contacts (email + call) per day
    brand_assets: List[BrandAsset] = [] # populated from tenant_assets table


# ---------------------------------------------------------------------------
# Local JSON store (Phase 1–4)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]   # growth-bizon-sales-ai/
_TENANTS_FILE = _REPO_ROOT / "tenants.json"
_lock = threading.Lock()

_SEED: dict = {
    "tenant_001": {
        "tenant_id": "tenant_001",
        "company_name": "Growth Bizon",
        "timezone": "America/Chicago",
        "language": "en",
        "geo_radius_miles": 50,
        "geo_center": "Houston, TX",
        "scraping_keywords": ["contractor no website Houston"],
        "lead_criteria": {
            "min_rating": 3.5,
            "min_reviews": 10,
            "max_reviews": None,
            "has_website": False,
            "company_size": "small",
            "industries": ["General Contractor"],
            "exclude_keywords": [],
        },
        "sender_name": "Carlos Rodriguez",
        "sender_email": "carlos@growthbizon.com",
        "owner_whatsapp": "+15551234567",
        "owner_name": "Carlos",
        "urgent_alert_threshold_usd": 5000,
        "rag_collection": "rag_tenant_001",
        "active": True,
        "daily_contact_cap": 50,
        "brand_assets": [],
    }
}


def _load_all() -> dict:
    if not _TENANTS_FILE.exists():
        return dict(_SEED)
    with open(_TENANTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_all(data: dict) -> None:
    with open(_TENANTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Public API (same signatures as the Supabase Phase 5 contract)
# ---------------------------------------------------------------------------


def load_tenant_config(tenant_id: str) -> TenantConfig:
    """Load TenantConfig from local JSON store. Called at start of every agent run."""
    data = _load_all()
    if tenant_id not in data:
        raise KeyError(f"Tenant not found: {tenant_id!r}")
    return TenantConfig(**data[tenant_id])


def get_all_active_tenants() -> List[TenantConfig]:
    """Return all active tenants. Used by the scheduler."""
    data = _load_all()
    return [TenantConfig(**v) for v in data.values() if v.get("active", True)]


def save_tenant_config(config: TenantConfig) -> None:
    """Persist a TenantConfig to the local JSON store (create or update)."""
    with _lock:
        data = _load_all()
        data[config.tenant_id] = config.model_dump(mode="json")
        _save_all(data)
    logger.info("save_tenant_config | tenant=%s", config.tenant_id)
