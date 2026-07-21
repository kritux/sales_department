"""
Google Maps scraper using Playwright (headless=True).

Scrapes business listings for a search query and returns them as a list of
dicts that match the Lead schema fields (score=0; id/tenant_id set by caller).

Security rules enforced (CLAUDE.md):
  - time.sleep(random.uniform(2, 5)) between every result click
  - Hard cap: MAX_LEADS_PER_SESSION = 100
  - User-agent rotated on every run from USER_AGENTS pool
  - DRY_RUN=true → synthetic stubs, no browser launched

CLI (run from backend/):
  python tools/maps_scraper.py --query "contractor no website Houston" --limit 20
  python tools/maps_scraper.py --query "restaurant Houston TX" --limit 10 --dry-run
"""

import argparse
import json
import logging
import random
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote_plus

from config.settings import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_LEADS_PER_SESSION = 100

# Realistic pool — one is picked at random per run (CLAUDE.md rule 6)
USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
]

# Google Maps DOM selectors — ordered by stability (most to least stable)
_RESULT_CARD_SELECTOR = "div[role='feed'] > div > div[jsaction]"

# Regex to extract lat/lng from Google Maps URL: /@lat,lng,zoom/
_LAT_LNG_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+),")
_CARD_NAME_SELECTORS = [
    "div.qBF1Pd",
    "span.fontHeadlineSmall",
    ".NrDZNb .fontHeadlineSmall",
]
_DETAIL_NAME_SELECTORS = [
    "h1.DUwDvf",
    "h1[class*='fontHeadlineLarge']",
    "h1",
]

_REPO_ROOT = Path(__file__).resolve().parents[2]   # growth-bizon-sales-ai/
_LOGS_ROOT = _REPO_ROOT / "logs"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _get_logger(tenant_id: str = "scraper") -> logging.Logger:
    log_dir = _LOGS_ROOT / tenant_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.log"

    logger = logging.getLogger(f"maps_scraper.{tenant_id}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _safe_text(page, selector: str, default: str = "") -> str:
    """Query selector and return inner text, never raises."""
    try:
        el = page.query_selector(selector)
        return el.inner_text().strip() if el else default
    except Exception:
        return default


def _first_text(page, selectors: List[str], default: str = "") -> str:
    """Try each selector in order, return first non-empty match."""
    for sel in selectors:
        val = _safe_text(page, sel)
        if val:
            return val
    return default


def _extract_city_state(address: str):
    """
    Best-effort city/state extraction from a Google Maps address string.

    Handles common formats:
      "123 Main St, Houston, TX 77001, USA"  → ("Houston", "TX")
      "Houston, TX"                           → ("Houston", "TX")
      ""                                      → ("", "")
    """
    if not address:
        return "", ""

    parts = [p.strip() for p in address.split(",")]
    if len(parts) < 2:
        return "", ""

    city = parts[-3] if len(parts) >= 3 else parts[-2]
    state_part = (parts[-2] if len(parts) >= 3 else parts[-1]).strip()
    state = state_part.split()[0][:2].upper() if state_part else ""
    return city.strip(), state


def _extract_lat_lng(page) -> Tuple[Optional[float], Optional[float]]:
    """
    Extract WGS-84 lat/lng from the Google Maps URL after a detail panel opens.

    Google Maps updates the browser URL to /@lat,lng,zoom when displaying a
    listing. Parsing the URL is more reliable than DOM scraping for coordinates.

    Returns (lat, lng) floats, or (None, None) if the pattern is absent.
    """
    try:
        url = page.url
        m = _LAT_LNG_RE.search(url)
        if m:
            return float(m.group(1)), float(m.group(2))
    except Exception:
        pass
    return None, None


def _extract_detail(page) -> Dict:
    """
    Extract all available Lead fields from an open Google Maps detail panel.
    All selectors have safe fallbacks — never raises.
    email is always None (Google Maps does not expose it).
    score is always 0 (scored downstream by lead_filter.py).
    """
    now = datetime.utcnow().isoformat()

    name = _first_text(page, _DETAIL_NAME_SELECTORS)
    category = (
        _safe_text(page, "button.DkEaL")
        or _safe_text(page, "[jsaction*='category']")
    )

    # Rating
    rating = None
    try:
        rating_raw = (
            _safe_text(page, "div.F7nice span[aria-hidden='true']")
            or _safe_text(page, "span.ceNzKf[aria-label*='stars']")
        )
        if rating_raw:
            rating = float(rating_raw.replace(",", "."))
    except (ValueError, AttributeError):
        pass

    # Review count
    review_count = None
    try:
        rc_raw = (
            _safe_text(page, "div.F7nice span[aria-label*='review']")
            or _safe_text(page, "span[aria-label*='reviews']")
        )
        digits = "".join(c for c in rc_raw if c.isdigit())
        review_count = int(digits) if digits else None
    except (ValueError, AttributeError):
        pass

    # Address
    address = ""
    try:
        addr_btn = page.query_selector("button[data-item-id='address']")
        if addr_btn:
            label = addr_btn.get_attribute("aria-label") or ""
            address = label.replace("Address: ", "").strip()
    except Exception:
        pass

    city, state = _extract_city_state(address)

    # Coordinates — parsed from URL, available once detail panel is open
    lat, lng = _extract_lat_lng(page)

    # Phone — data-item-id="phone:tel:+1XXXXXXXXXX"
    phone = None
    try:
        phone_btn = page.query_selector("button[data-item-id^='phone:tel:']")
        if phone_btn:
            raw = phone_btn.get_attribute("data-item-id") or ""
            phone = raw.replace("phone:tel:", "").strip() or None
    except Exception:
        pass

    # Website
    website = None
    try:
        web_el = page.query_selector("a[data-item-id='authority']")
        if web_el:
            website = web_el.get_attribute("href") or None
    except Exception:
        pass

    return {
        "company_name": name,
        "address": address,
        "city": city,
        "state": state,
        "phone": phone,
        "email": None,
        "website": website,
        "rating": rating,
        "review_count": review_count,
        "category": category,
        "lat": lat,
        "lng": lng,
        "score": 0,
        "source": "google_maps",
        "status": "new",
        "last_contact_at": None,
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }


def _scroll_results_panel(page, panel_selector: str, times: int = 3) -> None:
    """Scroll the results sidebar to trigger lazy-loading of more listings."""
    for _ in range(times):
        try:
            panel = page.query_selector(panel_selector)
            if panel:
                panel.evaluate("el => el.scrollBy(0, 600)")
                time.sleep(random.uniform(0.8, 1.5))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Dry-run stubs
# ---------------------------------------------------------------------------


def _dry_run_stubs(query: str, limit: int, tenant_id: str) -> List[Dict]:
    """
    Return synthetic Lead dicts for dry-run mode.
    Capped at 5 entries — enough to verify field structure without bloat.
    """
    now = datetime.utcnow().isoformat()
    count = min(limit, 5)
    # Houston city center: 29.7604° N, -95.3698° W
    # Stubs spread ±0.02° (~2 km) so coverage map shows useful dispersion
    _BASE_LAT = 29.7604
    _BASE_LNG = -95.3698
    _OFFSETS = [(-0.02, 0.01), (0.01, -0.015), (0.015, 0.02), (-0.01, -0.02), (0.02, 0.005)]
    return [
        {
            "tenant_id": tenant_id,
            "company_name": f"[DRY_RUN] Business {i + 1}",
            "address": f"{100 + i} Main St, Houston, TX 7700{i}",
            "city": "Houston",
            "state": "TX",
            "phone": f"+17135550{i:03d}",
            "email": None,
            "website": None,
            "rating": round(3.5 + (i % 3) * 0.5, 1),
            "review_count": 10 + i * 5,
            "category": "General Contractor",
            "lat": round(_BASE_LAT + _OFFSETS[i][0], 6),
            "lng": round(_BASE_LNG + _OFFSETS[i][1], 6),
            "score": 0,
            "source": "google_maps",
            "status": "new",
            "last_contact_at": None,
            "notes": f"dry_run stub — query: {query}",
            "created_at": now,
            "updated_at": now,
        }
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scrape_google_maps(
    query: str,
    limit: int = 20,
    tenant_id: str = "unknown",
    dry_run: Optional[bool] = None,
) -> List[Dict]:
    """
    Scrape Google Maps for the given search query.

    Args:
        query:      Search string, e.g. "contractor no website Houston TX".
        limit:      Max results to return. Hard-capped at MAX_LEADS_PER_SESSION.
        tenant_id:  Used for per-tenant log isolation.
        dry_run:    True  → synthetic stubs, no browser.
                    None  → falls back to settings.dry_run.

    Returns:
        List of dicts with Lead schema fields. id and tenant_id are set by
        the caller (scout.py) when writing to Supabase.
    """
    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run
    effective_limit = min(limit, MAX_LEADS_PER_SESSION)
    logger = _get_logger(tenant_id)

    logger.info(
        "Scraper starting | tenant=%s | query=%r | limit=%d | dry_run=%s",
        tenant_id, query, effective_limit, is_dry_run,
    )

    if is_dry_run:
        stubs = _dry_run_stubs(query, effective_limit, tenant_id)
        logger.info(
            "[DRY_RUN] Returning %d synthetic stubs — no browser launched", len(stubs)
        )
        return stubs

    # ------------------------------------------------------------------
    # Production path — lazy import keeps dry-run tests fast
    # ------------------------------------------------------------------
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    user_agent = random.choice(USER_AGENTS)
    logger.info("User-agent: %s…", user_agent[:72])

    leads: List[Dict] = []
    seen_names: Set[str] = set()
    url = f"https://www.google.com/maps/search/{quote_plus(query)}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        # Mask navigator.webdriver to reduce detection surface
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        try:
            logger.info("Navigating to %s", url)
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(random.uniform(2, 4))

            # Accept cookie consent if present (EU regions)
            try:
                consent = page.query_selector("button[aria-label*='Accept']")
                if consent:
                    consent.click()
                    time.sleep(1)
            except Exception:
                pass

            panel_selector = "div[role='feed']"
            try:
                page.wait_for_selector(panel_selector, timeout=15_000)
            except Exception:
                logger.warning("Results panel not found — layout may have changed")

            scroll_rounds = 0
            max_scroll_rounds = 20

            while len(leads) < effective_limit and scroll_rounds < max_scroll_rounds:
                cards = page.query_selector_all(_RESULT_CARD_SELECTOR)
                new_card_found = False

                for card in cards:
                    if len(leads) >= effective_limit:
                        break

                    try:
                        # Peek at the name without clicking, skip duplicates
                        preview_name = ""
                        for sel in _CARD_NAME_SELECTORS:
                            el = card.query_selector(sel)
                            if el:
                                preview_name = el.inner_text().strip()
                                break

                        if not preview_name or preview_name in seen_names:
                            continue

                        new_card_found = True
                        card.click()

                        # Required rate limit — CLAUDE.md rule 4
                        time.sleep(random.uniform(2, 5))

                        try:
                            page.wait_for_selector("h1", timeout=8_000)
                        except Exception:
                            logger.debug(
                                "Detail panel did not load for '%s', skipping",
                                preview_name,
                            )
                            page.go_back(wait_until="domcontentloaded", timeout=15_000)
                            time.sleep(random.uniform(1, 2))
                            continue

                        detail = _extract_detail(page)
                        if not detail["company_name"]:
                            detail["company_name"] = preview_name
                        detail["tenant_id"] = tenant_id

                        if detail["company_name"] in seen_names:
                            page.go_back(wait_until="domcontentloaded", timeout=15_000)
                            time.sleep(random.uniform(1, 2))
                            continue

                        seen_names.add(detail["company_name"])
                        leads.append(detail)

                        logger.info(
                            "[%d/%d] %s | %s, %s | rating=%s | website=%s",
                            len(leads), effective_limit,
                            detail["company_name"],
                            detail["city"],
                            detail["state"],
                            detail["rating"],
                            "yes" if detail["website"] else "no",
                        )

                        page.go_back(wait_until="domcontentloaded", timeout=15_000)
                        time.sleep(random.uniform(1.5, 3))

                    except Exception as exc:
                        logger.error("Card processing error: %s", exc)
                        try:
                            page.go_back(wait_until="domcontentloaded", timeout=10_000)
                            time.sleep(1)
                        except Exception:
                            pass

                _scroll_results_panel(page, panel_selector, times=3)
                scroll_rounds += 1

                if not new_card_found:
                    logger.info("No new cards after scroll round %d — stopping", scroll_rounds)
                    break

        except Exception as exc:
            logger.error("Fatal scraper error: %s", exc)
        finally:
            context.close()
            browser.close()

    logger.info(
        "Scrape complete | tenant=%s | leads=%d | query=%r",
        tenant_id, len(leads), query,
    )
    return leads


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape Google Maps for business leads."
    )
    parser.add_argument(
        "--query", required=True,
        help="Search query, e.g. 'contractor no website Houston TX'",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help=f"Max leads to return (hard cap: {MAX_LEADS_PER_SESSION})",
    )
    parser.add_argument(
        "--tenant", default="unknown",
        help="Tenant ID for log isolation, e.g. tenant_001",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Return synthetic stubs without launching a browser",
    )
    args = parser.parse_args()

    effective_dry_run = args.dry_run or settings.dry_run

    results = scrape_google_maps(
        query=args.query,
        limit=args.limit,
        tenant_id=args.tenant,
        dry_run=effective_dry_run,
    )
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
