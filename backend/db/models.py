"""
Contract 2 — LeadSchema (TEAM.md).
Scout produces Lead objects. Comms, Director, and Frontend consume them.
Do not change fields without Tech Lead approval.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class Lead(BaseModel):
    id: str                     # UUID, set by filter_leads() or Supabase
    tenant_id: str
    company_name: str
    address: str
    city: str
    state: str
    phone: Optional[str]
    email: Optional[str]
    website: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]
    category: str
    score: int                  # 0-100, assigned by lead_filter.py
    source: Literal["google_maps", "yelp", "manual"] = "google_maps"
    status: Literal[
        "new",
        "contacted",
        "responded",
        "meeting_set",
        "closed_won",
        "closed_lost",
        "no_response",
    ] = "new"
    lat: Optional[float] = None   # WGS-84 latitude from Google Maps URL
    lng: Optional[float] = None   # WGS-84 longitude from Google Maps URL
    last_contact_at: Optional[datetime] = None
    notes: str = ""
    created_at: datetime
    updated_at: datetime
