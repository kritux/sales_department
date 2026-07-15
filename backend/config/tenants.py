"""
Contract 1 — TenantConfig (TEAM.md).
Every agent receives a TenantConfig object. Never pass raw dicts downstream.
Do not change fields without Tech Lead approval.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel


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


def load_tenant_config(tenant_id: str) -> TenantConfig:
    """Load TenantConfig from Supabase. Called at start of every agent run."""
    raise NotImplementedError("Supabase client not yet wired — implement in Phase 5")


def get_all_active_tenants() -> List[TenantConfig]:
    """Return all active tenants. Used by the scheduler."""
    raise NotImplementedError("Supabase client not yet wired — implement in Phase 5")
