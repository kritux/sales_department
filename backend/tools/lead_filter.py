"""
Score raw lead dicts 0-100 against a tenant's LeadCriteria and return
qualified Lead objects sorted by score DESC.

Scoring rules (max possible = 100):
  +20 / -20  has_website  — no website = good prospect; has website = penalty
  +30        review_count — scaled linearly up to REVIEW_SCALE_MAX reviews
  +20 / +10  rating       — >4.0 → +20; >3.5 → +10
  +30        industry     — category substring-matches any entry in criteria.industries

Disqualifiers (score forced to 0, lead excluded regardless of threshold):
  - company_name or category contains any criteria.exclude_keywords entry

Threshold: only leads with score > SCORE_FLOOR (30) are returned.

Usage:
    from tools.lead_filter import filter_leads, score_lead
    from config.tenants import LeadCriteria

    criteria = LeadCriteria(industries=["contractor"], exclude_keywords=["chain"])
    leads = filter_leads(raw_lead_dicts, criteria, tenant_id="tenant_001")
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from config.tenants import LeadCriteria
from db.models import Lead

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCORE_FLOOR = 30           # leads at or below this score are excluded
REVIEW_SCALE_MAX = 100     # review count that earns the full +30 review bonus

# Individual component maximums (must sum to 100)
_WEBSITE_BONUS = 20
_WEBSITE_PENALTY = -20
_REVIEW_MAX = 30
_RATING_HIGH = 20          # rating > 4.0
_RATING_MID = 10           # rating > 3.5
_INDUSTRY_BONUS = 30


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_lead(lead_dict: Dict, criteria: LeadCriteria) -> int:
    """
    Score a single raw lead dict against LeadCriteria.

    Returns an int in [0, 100].
    Returns 0 immediately if any exclude_keyword matches company_name or category.
    """
    company_name = (lead_dict.get("company_name") or "").lower()
    category = (lead_dict.get("category") or "").lower()
    searchable = f"{company_name} {category}"

    # Hard disqualifier — exclude keyword match → score 0
    for kw in criteria.exclude_keywords:
        if kw.lower() in searchable:
            return 0

    score = 0

    # --- Website (+20 / -20) -------------------------------------------
    website = lead_dict.get("website")
    if not website:
        score += _WEBSITE_BONUS
    else:
        score += _WEBSITE_PENALTY

    # --- Review count (max +30, linear up to REVIEW_SCALE_MAX) ----------
    review_count = lead_dict.get("review_count") or 0
    if review_count > 0:
        score += min(_REVIEW_MAX, int(review_count / REVIEW_SCALE_MAX * _REVIEW_MAX))

    # --- Rating (+20 if >4.0, +10 if >3.5) ------------------------------
    rating = lead_dict.get("rating")
    if rating is not None:
        if rating > 4.0:
            score += _RATING_HIGH
        elif rating > 3.5:
            score += _RATING_MID

    # --- Industry match (+30) -------------------------------------------
    if criteria.industries:
        for industry in criteria.industries:
            if industry.lower() in category or category in industry.lower():
                score += _INDUSTRY_BONUS
                break

    return max(0, min(100, score))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def filter_leads(
    raw_leads: List[Dict],
    criteria: LeadCriteria,
    tenant_id: str,
) -> List[Lead]:
    """
    Score every raw lead dict, discard those at or below SCORE_FLOOR,
    hydrate survivors into Lead objects, and return sorted by score DESC.

    Args:
        raw_leads:  List of dicts from maps_scraper.scrape_google_maps().
        criteria:   LeadCriteria from TenantConfig.lead_criteria.
        tenant_id:  Used to stamp tenant_id on every Lead.

    Returns:
        List[Lead] with score > SCORE_FLOOR, sorted highest score first.
    """
    now = datetime.utcnow()
    qualified: List[Lead] = []

    for raw in raw_leads:
        lead_score = score_lead(raw, criteria)
        if lead_score <= SCORE_FLOOR:
            continue

        lead_data = {**raw}
        lead_data["score"] = lead_score
        lead_data["tenant_id"] = tenant_id

        # Ensure required fields have safe defaults if scraper left them absent
        if not lead_data.get("id"):
            lead_data["id"] = str(uuid.uuid4())
        if not lead_data.get("company_name"):
            lead_data["company_name"] = ""
        if not lead_data.get("address"):
            lead_data["address"] = ""
        if not lead_data.get("city"):
            lead_data["city"] = ""
        if not lead_data.get("state"):
            lead_data["state"] = ""
        if not lead_data.get("category"):
            lead_data["category"] = ""
        if not lead_data.get("created_at"):
            lead_data["created_at"] = now
        if not lead_data.get("updated_at"):
            lead_data["updated_at"] = now

        try:
            qualified.append(Lead(**lead_data))
        except Exception:
            # Malformed dict — skip silently; logging is caller's responsibility
            continue

    return sorted(qualified, key=lambda lead: lead.score, reverse=True)
