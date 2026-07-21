"""
Tests for backend/tools/maps_scraper.py.
All tests run without launching a real browser (dry-run / pure unit level).
Playwright is never imported in this test module.
"""

import random
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.maps_scraper import (
    MAX_LEADS_PER_SESSION,
    USER_AGENTS,
    _LAT_LNG_RE,
    _dry_run_stubs,
    _extract_city_state,
    _extract_lat_lng,
    scrape_google_maps,
)

# Every Lead dict returned by the scraper must contain these keys
REQUIRED_LEAD_FIELDS = {
    "company_name", "address", "city", "state",
    "phone", "email", "website", "rating", "review_count",
    "category", "lat", "lng", "score", "source", "status",
    "last_contact_at", "notes", "created_at", "updated_at",
}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_max_leads_cap_is_100(self):
        assert MAX_LEADS_PER_SESSION == 100

    def test_user_agent_pool_has_enough_variety(self):
        assert len(USER_AGENTS) >= 5

    def test_all_user_agents_are_nonempty_strings(self):
        for ua in USER_AGENTS:
            assert isinstance(ua, str) and len(ua) > 20

    def test_user_agents_are_unique(self):
        assert len(USER_AGENTS) == len(set(USER_AGENTS))


# ---------------------------------------------------------------------------
# _extract_city_state — pure function, no I/O
# ---------------------------------------------------------------------------

class TestExtractCityState:
    def test_full_us_address(self):
        city, state = _extract_city_state("123 Main St, Houston, TX 77001, USA")
        assert city == "Houston"
        assert state == "TX"

    def test_suite_in_address(self):
        city, state = _extract_city_state("456 Oak Ave, Suite 100, Dallas, TX 75201, USA")
        assert city == "Dallas"
        assert state == "TX"

    def test_two_part_address(self):
        city, state = _extract_city_state("Houston, TX")
        assert isinstance(city, str)
        assert isinstance(state, str)

    def test_three_part_address(self):
        city, state = _extract_city_state("Houston, TX, USA")
        assert city == "Houston"
        assert state == "TX"

    def test_empty_string_returns_empty(self):
        city, state = _extract_city_state("")
        assert city == ""
        assert state == ""

    def test_state_is_at_most_two_chars(self):
        _, state = _extract_city_state("123 Elm St, Miami, FL 33101, USA")
        assert len(state) <= 2

    def test_state_is_uppercase(self):
        _, state = _extract_city_state("100 Pine Rd, Austin, TX 78701, USA")
        assert state == state.upper()

    def test_no_comma_returns_empty(self):
        city, state = _extract_city_state("NoCommaAddress")
        assert city == ""
        assert state == ""


# ---------------------------------------------------------------------------
# _dry_run_stubs — pure function
# ---------------------------------------------------------------------------

class TestDryRunStubs:
    def test_returns_list(self):
        assert isinstance(_dry_run_stubs("query", 3, "tenant_001"), list)

    def test_respects_limit(self):
        stubs = _dry_run_stubs("test", 2, "tenant_001")
        assert len(stubs) == 2

    def test_caps_at_five(self):
        # Dry-run stubs cap at 5 to stay lightweight
        stubs = _dry_run_stubs("test", 100, "tenant_001")
        assert len(stubs) <= 5

    def test_zero_limit_returns_empty(self):
        assert _dry_run_stubs("test", 0, "tenant_001") == []

    def test_has_all_required_lead_fields(self):
        stubs = _dry_run_stubs("q", 1, "tenant_001")
        for field in REQUIRED_LEAD_FIELDS:
            assert field in stubs[0], f"Missing Lead field: {field}"

    def test_source_is_google_maps(self):
        stubs = _dry_run_stubs("q", 1, "tenant_001")
        assert stubs[0]["source"] == "google_maps"

    def test_status_is_new(self):
        stubs = _dry_run_stubs("q", 1, "tenant_001")
        assert stubs[0]["status"] == "new"

    def test_score_is_zero(self):
        # lead_filter.py assigns score downstream — scraper always returns 0
        stubs = _dry_run_stubs("q", 1, "tenant_001")
        assert stubs[0]["score"] == 0

    def test_email_is_none(self):
        # Google Maps does not expose email addresses
        stubs = _dry_run_stubs("q", 1, "tenant_001")
        assert stubs[0]["email"] is None

    def test_tenant_id_is_propagated(self):
        stubs = _dry_run_stubs("q", 3, "tenant_042")
        for stub in stubs:
            assert stub["tenant_id"] == "tenant_042"

    def test_stubs_are_distinct(self):
        stubs = _dry_run_stubs("q", 3, "tenant_001")
        names = [s["company_name"] for s in stubs]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# scrape_google_maps — dry-run mode (no Playwright)
# ---------------------------------------------------------------------------

class TestScrapeGoogleMapsDryRun:
    def test_returns_list(self):
        result = scrape_google_maps("contractor Houston TX", dry_run=True)
        assert isinstance(result, list)

    def test_limit_is_respected(self):
        result = scrape_google_maps("contractor Houston", limit=2, dry_run=True)
        assert len(result) <= 2

    def test_hard_cap_enforced_regardless_of_limit_arg(self):
        result = scrape_google_maps("plumber", limit=9999, dry_run=True)
        assert len(result) <= MAX_LEADS_PER_SESSION

    def test_result_items_have_required_fields(self):
        result = scrape_google_maps("restaurant Dallas TX", limit=1, dry_run=True)
        if result:
            for field in REQUIRED_LEAD_FIELDS:
                assert field in result[0], f"Missing field: {field}"

    def test_tenant_id_is_set_in_results(self):
        result = scrape_google_maps(
            "contractor", limit=1, tenant_id="tenant_007", dry_run=True
        )
        if result:
            assert result[0]["tenant_id"] == "tenant_007"

    def test_source_is_google_maps(self):
        result = scrape_google_maps("test", limit=1, dry_run=True)
        if result:
            assert result[0]["source"] == "google_maps"

    def test_score_zero_in_dry_run(self):
        result = scrape_google_maps("test", limit=1, dry_run=True)
        if result:
            assert result[0]["score"] == 0

    def test_falls_back_to_settings_dry_run(self, monkeypatch):
        import tools.maps_scraper as mod
        monkeypatch.setattr(mod.settings, "dry_run", True)
        result = scrape_google_maps("restaurant Miami", dry_run=None)
        assert isinstance(result, list)

    def test_playwright_not_imported_in_dry_run(self):
        # Playwright import is lazy — dry-run must never trigger it
        import sys
        before = set(sys.modules.keys())
        scrape_google_maps("test query", dry_run=True)
        after = set(sys.modules.keys())
        new_modules = after - before
        playwright_loaded = any("playwright" in m for m in new_modules)
        assert not playwright_loaded

    def test_empty_query_returns_list(self):
        result = scrape_google_maps("", dry_run=True)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# User-agent rotation
# ---------------------------------------------------------------------------

class TestUserAgentRotation:
    def test_all_user_agents_are_reachable_by_random_choice(self):
        """Every agent in the pool must be reachable via random.choice."""
        selected = {random.choice(USER_AGENTS) for _ in range(200)}
        # With 8 agents and 200 draws, every agent should appear at least once
        # (probability of any single agent never appearing ≈ (7/8)^200 ≈ 8e-12)
        assert selected == set(USER_AGENTS)

    def test_different_runs_may_pick_different_agents(self):
        # Statistical: with 8 agents and 20 draws, collision of all being same is negligible
        selected = {random.choice(USER_AGENTS) for _ in range(20)}
        assert len(selected) > 1


# ---------------------------------------------------------------------------
# Lat/lng regex
# ---------------------------------------------------------------------------

class TestLatLngRegex:
    def test_matches_standard_url(self):
        url = "https://www.google.com/maps/place/Acme+Co/@29.7604,-95.3698,17z/data=..."
        m = _LAT_LNG_RE.search(url)
        assert m is not None
        assert float(m.group(1)) == pytest.approx(29.7604)
        assert float(m.group(2)) == pytest.approx(-95.3698)

    def test_matches_negative_lat(self):
        url = "https://www.google.com/maps/place/Foo/@-33.8688,151.2093,15z/data=..."
        m = _LAT_LNG_RE.search(url)
        assert m is not None
        assert float(m.group(1)) == pytest.approx(-33.8688)

    def test_no_match_without_at_prefix(self):
        url = "https://www.google.com/maps/search/contractor+Houston"
        assert _LAT_LNG_RE.search(url) is None


# ---------------------------------------------------------------------------
# _extract_lat_lng
# ---------------------------------------------------------------------------

class TestExtractLatLng:
    def _mock_page(self, url: str):
        page = MagicMock()
        page.url = url
        return page

    def test_extracts_from_valid_url(self):
        page = self._mock_page(
            "https://www.google.com/maps/place/Foo/@29.7604,-95.3698,17z/"
        )
        lat, lng = _extract_lat_lng(page)
        assert lat == pytest.approx(29.7604)
        assert lng == pytest.approx(-95.3698)

    def test_returns_none_none_for_search_url(self):
        page = self._mock_page("https://www.google.com/maps/search/contractor+Houston")
        lat, lng = _extract_lat_lng(page)
        assert lat is None
        assert lng is None

    def test_returns_none_none_on_exception(self):
        page = MagicMock()
        page.url = MagicMock(side_effect=Exception("browser closed"))
        lat, lng = _extract_lat_lng(page)
        assert lat is None
        assert lng is None


# ---------------------------------------------------------------------------
# Dry-run stubs — lat/lng fields
# ---------------------------------------------------------------------------

class TestDryRunStubsLatLng:
    def test_stubs_have_lat_field(self):
        stubs = _dry_run_stubs("q", 3, "tenant_001")
        for stub in stubs:
            assert "lat" in stub

    def test_stubs_have_lng_field(self):
        stubs = _dry_run_stubs("q", 3, "tenant_001")
        for stub in stubs:
            assert "lng" in stub

    def test_stub_lat_is_float(self):
        stubs = _dry_run_stubs("q", 3, "tenant_001")
        for stub in stubs:
            assert isinstance(stub["lat"], float)

    def test_stub_lng_is_float(self):
        stubs = _dry_run_stubs("q", 3, "tenant_001")
        for stub in stubs:
            assert isinstance(stub["lng"], float)

    def test_stub_lat_is_near_houston(self):
        # Houston is ~29.76°N — all stubs should be within 0.1°
        stubs = _dry_run_stubs("q", 5, "tenant_001")
        for stub in stubs:
            assert abs(stub["lat"] - 29.7604) < 0.1

    def test_stub_lng_is_near_houston(self):
        # Houston is ~-95.37°W — all stubs should be within 0.1°
        stubs = _dry_run_stubs("q", 5, "tenant_001")
        for stub in stubs:
            assert abs(stub["lng"] - (-95.3698)) < 0.1

    def test_stubs_have_distinct_coordinates(self):
        stubs = _dry_run_stubs("q", 5, "tenant_001")
        coords = [(s["lat"], s["lng"]) for s in stubs]
        assert len(coords) == len(set(coords))


# ---------------------------------------------------------------------------
# Lead model — lat/lng fields propagate through filter_leads
# ---------------------------------------------------------------------------

class TestLatLngPassThroughFilterLeads:
    def test_lat_lng_survive_filter_leads(self):
        """Coordinates scraped by maps_scraper must survive into qualified Lead objects."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from tools.lead_filter import filter_leads
        from config.tenants import LeadCriteria

        criteria = LeadCriteria(
            industries=["contractor"],
            exclude_keywords=[],
            min_rating=0.0,
            min_reviews=0,
        )
        stubs = _dry_run_stubs("q", 2, "tenant_001")
        # Bump review_count and remove website so stubs score above SCORE_FLOOR
        for s in stubs:
            s["review_count"] = 50
            s["website"] = None

        leads = filter_leads(stubs, criteria, "tenant_001")
        assert len(leads) > 0
        for lead in leads:
            assert lead.lat is not None
            assert lead.lng is not None
            assert isinstance(lead.lat, float)
            assert isinstance(lead.lng, float)
