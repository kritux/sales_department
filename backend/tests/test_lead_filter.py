"""
Tests for backend/tools/lead_filter.py.
No external dependencies — pure scoring logic only.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import LeadCriteria
from db.models import Lead
from tools.lead_filter import (
    REVIEW_SCALE_MAX,
    SCORE_FLOOR,
    filter_leads,
    score_lead,
    _INDUSTRY_BONUS,
    _RATING_HIGH,
    _RATING_MID,
    _REVIEW_MAX,
    _WEBSITE_BONUS,
    _WEBSITE_PENALTY,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime.utcnow().isoformat()


def _raw(
    company_name="Acme Contracting",
    category="General Contractor",
    website=None,
    rating=4.2,
    review_count=50,
    **kwargs,
) -> dict:
    """Return a minimal raw lead dict matching the maps_scraper output shape."""
    base = {
        "tenant_id": "tenant_001",
        "company_name": company_name,
        "address": "123 Main St, Houston, TX 77001",
        "city": "Houston",
        "state": "TX",
        "phone": "+17135550001",
        "email": None,
        "website": website,
        "rating": rating,
        "review_count": review_count,
        "category": category,
        "score": 0,
        "source": "google_maps",
        "status": "new",
        "last_contact_at": None,
        "notes": "",
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(kwargs)
    return base


def _criteria(**kwargs) -> LeadCriteria:
    return LeadCriteria(**kwargs)


# ---------------------------------------------------------------------------
# score_lead — constants
# ---------------------------------------------------------------------------

class TestScoreConstants:
    def test_component_scores_sum_to_100(self):
        total = _WEBSITE_BONUS + _REVIEW_MAX + _RATING_HIGH + _INDUSTRY_BONUS
        assert total == 100

    def test_score_floor_is_30(self):
        assert SCORE_FLOOR == 30

    def test_review_scale_max_is_100(self):
        assert REVIEW_SCALE_MAX == 100


# ---------------------------------------------------------------------------
# score_lead — website component
# ---------------------------------------------------------------------------

class TestWebsiteScoring:
    def test_no_website_gives_bonus(self):
        raw = _raw(website=None)
        score = score_lead(raw, _criteria())
        # Score must include the +20 website bonus
        # Isolate by zeroing other variables
        base = score_lead(_raw(website=None, rating=None, review_count=0), _criteria())
        assert base == _WEBSITE_BONUS

    def test_empty_string_website_counts_as_no_website(self):
        s = score_lead(_raw(website="", rating=None, review_count=0), _criteria())
        assert s == _WEBSITE_BONUS

    def test_has_website_gives_penalty(self):
        s = score_lead(_raw(website="https://example.com", rating=None, review_count=0), _criteria())
        assert s == 0  # -20 clamped to 0

    def test_website_penalty_reduces_score(self):
        no_site = score_lead(_raw(website=None), _criteria())
        has_site = score_lead(_raw(website="https://example.com"), _criteria())
        assert no_site > has_site

    def test_score_never_goes_below_zero(self):
        raw = _raw(website="https://x.com", rating=None, review_count=0)
        assert score_lead(raw, _criteria()) >= 0


# ---------------------------------------------------------------------------
# score_lead — review_count component
# ---------------------------------------------------------------------------

class TestReviewScoring:
    def test_zero_reviews_gives_no_bonus(self):
        s = score_lead(_raw(website=None, rating=None, review_count=0), _criteria())
        assert s == _WEBSITE_BONUS  # only website bonus

    def test_none_reviews_gives_no_bonus(self):
        s = score_lead(_raw(website=None, rating=None, review_count=None), _criteria())
        assert s == _WEBSITE_BONUS

    def test_100_reviews_gives_full_review_bonus(self):
        s = score_lead(_raw(website=None, rating=None, review_count=100), _criteria())
        assert s == _WEBSITE_BONUS + _REVIEW_MAX

    def test_200_reviews_still_capped_at_review_max(self):
        s = score_lead(_raw(website=None, rating=None, review_count=200), _criteria())
        assert s == _WEBSITE_BONUS + _REVIEW_MAX

    def test_50_reviews_gives_partial_bonus(self):
        s = score_lead(_raw(website=None, rating=None, review_count=50), _criteria())
        # 50/100 * 30 = 15
        assert s == _WEBSITE_BONUS + 15

    def test_1_review_gives_no_bonus_due_to_int_truncation(self):
        # 1/100 * 30 = 0.3 → int() truncates to 0
        s = score_lead(_raw(website=None, rating=None, review_count=1), _criteria())
        assert s == _WEBSITE_BONUS

    def test_review_score_increases_with_count(self):
        low = score_lead(_raw(website=None, rating=None, review_count=10), _criteria())
        mid = score_lead(_raw(website=None, rating=None, review_count=50), _criteria())
        high = score_lead(_raw(website=None, rating=None, review_count=100), _criteria())
        assert low < mid < high


# ---------------------------------------------------------------------------
# score_lead — rating component
# ---------------------------------------------------------------------------

class TestRatingScoring:
    def test_rating_above_4_gives_high_bonus(self):
        s = score_lead(_raw(website=None, rating=4.1, review_count=0), _criteria())
        assert s == _WEBSITE_BONUS + _RATING_HIGH

    def test_rating_exactly_4_does_not_qualify_for_high(self):
        s = score_lead(_raw(website=None, rating=4.0, review_count=0), _criteria())
        # 4.0 is not > 4.0 → falls to mid check (4.0 is not > 3.5 either — wait)
        # 4.0 > 3.5 is True → mid bonus
        assert s == _WEBSITE_BONUS + _RATING_MID

    def test_rating_above_3_5_gives_mid_bonus(self):
        s = score_lead(_raw(website=None, rating=3.7, review_count=0), _criteria())
        assert s == _WEBSITE_BONUS + _RATING_MID

    def test_rating_exactly_3_5_gives_no_bonus(self):
        s = score_lead(_raw(website=None, rating=3.5, review_count=0), _criteria())
        # 3.5 is not > 3.5
        assert s == _WEBSITE_BONUS

    def test_low_rating_gives_no_bonus(self):
        s = score_lead(_raw(website=None, rating=2.0, review_count=0), _criteria())
        assert s == _WEBSITE_BONUS

    def test_none_rating_gives_no_bonus(self):
        s = score_lead(_raw(website=None, rating=None, review_count=0), _criteria())
        assert s == _WEBSITE_BONUS

    def test_high_rating_beats_mid_rating(self):
        high = score_lead(_raw(website=None, rating=4.5, review_count=0), _criteria())
        mid = score_lead(_raw(website=None, rating=3.8, review_count=0), _criteria())
        assert high > mid


# ---------------------------------------------------------------------------
# score_lead — industry match component
# ---------------------------------------------------------------------------

class TestIndustryScoring:
    def test_exact_match_gives_full_bonus(self):
        criteria = _criteria(industries=["general contractor"])
        s = score_lead(_raw(website=None, rating=None, review_count=0, category="General Contractor"), criteria)
        assert s == _WEBSITE_BONUS + _INDUSTRY_BONUS

    def test_partial_match_gives_bonus(self):
        criteria = _criteria(industries=["contractor"])
        s = score_lead(_raw(website=None, rating=None, review_count=0, category="General Contractor"), criteria)
        assert s == _WEBSITE_BONUS + _INDUSTRY_BONUS

    def test_no_match_gives_no_bonus(self):
        criteria = _criteria(industries=["plumber"])
        s = score_lead(_raw(website=None, rating=None, review_count=0, category="Restaurant"), criteria)
        assert s == _WEBSITE_BONUS

    def test_empty_industries_list_gives_no_bonus(self):
        criteria = _criteria(industries=[])
        s = score_lead(_raw(website=None, rating=None, review_count=0), criteria)
        assert s == _WEBSITE_BONUS

    def test_match_is_case_insensitive(self):
        criteria = _criteria(industries=["CONTRACTOR"])
        s = score_lead(_raw(website=None, rating=None, review_count=0, category="general contractor"), criteria)
        assert s == _WEBSITE_BONUS + _INDUSTRY_BONUS

    def test_only_first_match_counted(self):
        criteria = _criteria(industries=["contractor", "general"])
        s = score_lead(_raw(website=None, rating=None, review_count=0, category="General Contractor"), criteria)
        # Both match but bonus only applied once
        assert s == _WEBSITE_BONUS + _INDUSTRY_BONUS


# ---------------------------------------------------------------------------
# score_lead — exclude_keywords disqualifier
# ---------------------------------------------------------------------------

class TestExcludeKeywords:
    def test_exclude_keyword_in_company_name_returns_zero(self):
        criteria = _criteria(exclude_keywords=["chain"])
        raw = _raw(company_name="Big Chain Corp", website=None, rating=5.0, review_count=200)
        assert score_lead(raw, criteria) == 0

    def test_exclude_keyword_in_category_returns_zero(self):
        criteria = _criteria(exclude_keywords=["franchise"])
        raw = _raw(category="Fast Food Franchise", website=None, rating=5.0, review_count=200)
        assert score_lead(raw, criteria) == 0

    def test_exclude_keyword_match_is_case_insensitive(self):
        criteria = _criteria(exclude_keywords=["CHAIN"])
        raw = _raw(company_name="big chain corp", website=None, rating=5.0, review_count=200)
        assert score_lead(raw, criteria) == 0

    def test_no_exclude_keywords_does_not_disqualify(self):
        criteria = _criteria(exclude_keywords=[])
        raw = _raw(website=None, rating=4.5, review_count=100)
        assert score_lead(raw, criteria) > 0

    def test_non_matching_exclude_keyword_does_not_affect_score(self):
        criteria = _criteria(exclude_keywords=["McDonalds"])
        raw = _raw(company_name="Acme Contracting", website=None, rating=4.5, review_count=100)
        assert score_lead(raw, criteria) > 0


# ---------------------------------------------------------------------------
# score_lead — bounds
# ---------------------------------------------------------------------------

class TestScoreBounds:
    def test_perfect_lead_scores_100(self):
        criteria = _criteria(industries=["contractor"])
        raw = _raw(
            website=None,       # +20
            rating=4.5,         # +20
            review_count=100,   # +30
            category="General Contractor",  # +30
        )
        assert score_lead(raw, criteria) == 100

    def test_score_never_exceeds_100(self):
        criteria = _criteria(industries=["contractor"])
        raw = _raw(website=None, rating=5.0, review_count=9999, category="Contractor")
        assert score_lead(raw, criteria) <= 100

    def test_score_never_below_zero(self):
        criteria = _criteria()
        raw = _raw(website="https://x.com", rating=1.0, review_count=0)
        assert score_lead(raw, criteria) >= 0


# ---------------------------------------------------------------------------
# filter_leads
# ---------------------------------------------------------------------------

class TestFilterLeads:
    def test_returns_list(self):
        result = filter_leads([], _criteria(), "tenant_001")
        assert isinstance(result, list)

    def test_empty_input_returns_empty(self):
        assert filter_leads([], _criteria(), "tenant_001") == []

    def test_leads_above_floor_are_included(self):
        criteria = _criteria(industries=["contractor"])
        raw = _raw(website=None, rating=4.5, review_count=100, category="Contractor")
        # Score = 100 → well above 30
        result = filter_leads([raw], criteria, "tenant_001")
        assert len(result) == 1

    def test_leads_at_or_below_floor_are_excluded(self):
        # Score: has website (-20 clamped to 0, score=0) → excluded
        raw = _raw(website="https://x.com", rating=None, review_count=0)
        result = filter_leads([raw], _criteria(), "tenant_001")
        assert len(result) == 0

    def test_leads_exactly_at_floor_are_excluded(self):
        # Need a lead that scores exactly 30 — which is not possible with
        # our component values (20+10=30 is the smallest combo hitting floor).
        # 20 (no website) + 10 (rating 3.7) = 30 → excluded (not > 30)
        raw = _raw(website=None, rating=3.7, review_count=0)
        result = filter_leads([raw], _criteria(), "tenant_001")
        assert len(result) == 0

    def test_result_sorted_by_score_descending(self):
        criteria = _criteria(industries=["contractor"])
        high = _raw(website=None, rating=4.5, review_count=100, category="Contractor")  # 100
        mid = _raw(website=None, rating=4.5, review_count=50, category="Contractor")    # 85
        low = _raw(website=None, rating=3.7, review_count=50, category="Contractor")    # 75
        result = filter_leads([low, high, mid], criteria, "tenant_001")
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_returns_lead_objects_not_dicts(self):
        criteria = _criteria(industries=["contractor"])
        raw = _raw(website=None, rating=4.5, review_count=100, category="Contractor")
        result = filter_leads([raw], criteria, "tenant_001")
        assert all(isinstance(r, Lead) for r in result)

    def test_score_stamped_on_lead(self):
        criteria = _criteria(industries=["contractor"])
        raw = _raw(website=None, rating=4.5, review_count=100, category="Contractor")
        result = filter_leads([raw], criteria, "tenant_001")
        assert result[0].score == 100

    def test_tenant_id_stamped_on_lead(self):
        criteria = _criteria(industries=["contractor"])
        raw = _raw(website=None, rating=4.5, review_count=100, category="Contractor")
        result = filter_leads([raw], criteria, "tenant_042")
        assert result[0].tenant_id == "tenant_042"

    def test_id_is_set_when_missing(self):
        criteria = _criteria(industries=["contractor"])
        raw = _raw(website=None, rating=4.5, review_count=100, category="Contractor")
        raw.pop("id", None)
        result = filter_leads([raw], criteria, "tenant_001")
        assert result[0].id  # non-empty UUID

    def test_malformed_lead_is_skipped_silently(self):
        criteria = _criteria(industries=["contractor"])
        good = _raw(website=None, rating=4.5, review_count=100, category="Contractor")
        bad = {"completely": "wrong", "shape": True}
        # Should not raise; bad lead is skipped
        result = filter_leads([good, bad], criteria, "tenant_001")
        assert len(result) == 1

    def test_excluded_keywords_removes_lead(self):
        criteria = _criteria(
            industries=["contractor"],
            exclude_keywords=["chain"],
        )
        raw = _raw(
            company_name="Big Chain Contractors",
            website=None, rating=4.5, review_count=100, category="Contractor",
        )
        result = filter_leads([raw], criteria, "tenant_001")
        assert len(result) == 0

    def test_multiple_leads_all_above_floor_all_returned(self):
        criteria = _criteria(industries=["contractor"])
        raws = [
            _raw(website=None, rating=4.5, review_count=100, category="Contractor"),
            _raw(website=None, rating=4.1, review_count=80, category="Contractor"),
            _raw(website=None, rating=3.8, review_count=60, category="Contractor"),
        ]
        result = filter_leads(raws, criteria, "tenant_001")
        assert len(result) == 3
