#!/usr/bin/env python3
"""
BIZON — Command Center | Full Daily Cycle
Demonstrates the complete automated flow that cron.py runs at 7:00 AM.
DRY_RUN=true throughout — no external calls, no DB writes.
RAG queries hit ChromaDB live (reads only, zero side effects).

Run from the backend/ directory:
    PYTHONPATH=. python3 run_full_daily_cycle.py
"""

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

# ── Path setup ────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# Must be set before any project import so every tool reads it from settings.
os.environ["DRY_RUN"] = "true"

# ── Project imports ───────────────────────────────────────────────────────────
from config.tenants import TenantConfig, LeadCriteria          # noqa: E402
from db.models import Lead                                      # noqa: E402
from tools.maps_scraper import scrape_google_maps              # noqa: E402
from tools.lead_filter import filter_leads, SCORE_FLOOR        # noqa: E402
from tools.rag_query import query_rag                          # noqa: E402
from tools.email_tool import render_email, send_email          # noqa: E402
from tools.call_tool import call_prospect                      # noqa: E402
from tools.whatsapp_tool import send_whatsapp_summary          # noqa: E402

# ── Demo tenant ───────────────────────────────────────────────────────────────
DEMO_TENANT = TenantConfig(
    tenant_id="tenant_001",
    company_name="Growth Bizon",
    timezone="America/Chicago",
    language="en",
    geo_center="Houston, TX",
    geo_radius_miles=30,
    scraping_keywords=[
        "contractor no website Houston TX",
        "HVAC company no website Houston TX",
    ],
    lead_criteria=LeadCriteria(
        min_rating=3.5,
        min_reviews=5,
        industries=["contractor", "hvac", "plumbing", "electrical", "roofing"],
        exclude_keywords=["chain", "franchise"],
    ),
    sender_name="Carlos Mendez",
    sender_email="carlos@growthbizon.com",
    owner_whatsapp="+17135550001",
    owner_name="Carlos Mendez",
    rag_collection="rag_tenant_001",
    active=True,
)

# ── Display helpers ───────────────────────────────────────────────────────────
W = 68


def _banner() -> None:
    inner = W - 2
    print()
    print("╔" + "═" * inner + "╗")
    print("║" + "  BIZON — Command Center  |  FULL DAILY CYCLE".center(inner) + "║")
    print("║" + "  DRY_RUN MODE — zero external calls made".center(inner) + "║")
    print("╚" + "═" * inner + "╝")
    print()
    print(f"  Tenant:  {DEMO_TENANT.tenant_id} — {DEMO_TENANT.company_name}")
    print(f"  Started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Simulates: cron job at 7:00 AM {DEMO_TENANT.timezone}")


def _step(n: int, total: int, title: str) -> None:
    print()
    print("━" * W)
    print(f"  STEP {n}/{total}  ·  {title}")
    print("━" * W)


def _sub(text: str) -> None:
    print(f"  {text}")


def _block(text: str, indent: int = 4) -> None:
    prefix = " " * indent
    for line in text.splitlines():
        print(prefix + line)


# ── DailyReport ───────────────────────────────────────────────────────────────

@dataclass
class DailyReport:
    tenant_id: str
    date: str
    leads_scouted: int = 0
    leads_qualified: int = 0
    emails_sent: int = 0
    calls_made: int = 0
    responses: int = 0
    meetings_booked: int = 0
    top_lead: Optional[str] = None
    top_lead_score: int = 0
    rag_context_used: bool = False
    summary_text: str = ""


# ── Step implementations ──────────────────────────────────────────────────────

def step_rag_context(report: DailyReport) -> str:
    _step(1, 8, "RAG CONTEXT  (live ChromaDB read — not dry-run)")

    query = "What services does Growth Bizon offer and how much do they cost?"
    _sub(f"Collection:  {DEMO_TENANT.rag_collection}")
    _sub(f"Query:       {query!r}")
    print()

    rag = query_rag(DEMO_TENANT.tenant_id, query)

    top_score = rag.chunks[0].relevance_score if rag.chunks else 0.0
    _sub(f"Found:       {rag.found}")
    _sub(f"Top score:   {top_score:.4f}")
    _sub(f"Chunks:      {len(rag.chunks)}")
    print()
    _sub("Context retrieved from ChromaDB:")
    _block(rag.context or "[empty — run rag_loader.py to populate]")

    report.rag_context_used = rag.found
    return rag.context or ""


def step_scout(report: DailyReport) -> List[dict]:
    _step(2, 8, "SCOUT AGENT  (Google Maps scraper — dry-run stubs)")

    raw: List[dict] = []
    for kw in DEMO_TENANT.scraping_keywords:
        _sub(f"Scraping: {kw!r}")
        batch = scrape_google_maps(
            query=kw,
            tenant_id=DEMO_TENANT.tenant_id,
            limit=10,
            dry_run=True,
        )
        _sub(f"  → {len(batch)} raw results returned")
        raw.extend(batch)

    print()
    _sub(f"Total raw leads collected:  {len(raw)}")
    report.leads_scouted = len(raw)
    return raw


def step_filter(raw: List[dict], report: DailyReport) -> List[Lead]:
    _step(3, 8, "LEAD FILTER + SCORING")

    qualified = filter_leads(
        raw_leads=raw,
        criteria=DEMO_TENANT.lead_criteria,
        tenant_id=DEMO_TENANT.tenant_id,
    )

    _sub(f"Raw leads in:       {len(raw)}")
    _sub(f"Score floor:        > {SCORE_FLOOR}")
    _sub(f"Qualified leads:    {len(qualified)}")
    print()

    preview = qualified[:6]
    for lead in preview:
        _sub(f"  [{lead.score:3d}]  {lead.company_name:<32}  {lead.category}")
    if len(qualified) > 6:
        _sub(f"  ... and {len(qualified) - 6} more")

    if qualified:
        top = qualified[0]
        report.top_lead = top.company_name
        report.top_lead_score = top.score

    report.leads_qualified = len(qualified)
    return qualified


def step_email_cadence(
    qualified: List[Lead],
    rag_context: str,
    report: DailyReport,
) -> None:
    _step(4, 8, "EMAIL AGENT  (day-0 intro cadence — dry-run)")

    # Stubs don't carry real emails; assign placeholders so validation passes.
    leads_to_email = []
    import re as _re
    for i, lead in enumerate(qualified[:5]):
        slug = _re.sub(r"[^a-z0-9]", "", lead.company_name.lower())[:16] or f"biz{i + 1}"
        leads_to_email.append(
            lead.model_copy(update={"email": f"owner{i + 1}@{slug}.com"})
        )

    emails_sent = 0
    printed_preview = False

    for lead in leads_to_email:
        subject, body = render_email(lead, DEMO_TENANT, rag_context)
        result = send_email(lead, DEMO_TENANT, subject, body, dry_run=True)

        if not printed_preview:
            print()
            _sub("── Full email preview (top qualified lead) ──────────────────")
            _sub(f"  FROM:    {DEMO_TENANT.sender_name} <{DEMO_TENANT.sender_email}>")
            _sub(f"  TO:      {lead.email}")
            _sub(f"  SUBJECT: {subject}")
            _sub(f"  STATUS:  {result.status}")
            print()
            _sub("  BODY:")
            _block(body, indent=6)
            print()
            printed_preview = True

        if result.status in ("sent", "dry_run"):
            emails_sent += 1

    _sub(f"Emails dispatched (dry-run):  {emails_sent} / {len(leads_to_email)} leads contacted")
    report.emails_sent = emails_sent


def step_call_cadence(report: DailyReport) -> None:
    _step(5, 8, "CALL AGENT  (cadence day 7 — prospect call — dry-run)")

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    stale_lead = Lead(
        id="lead-demo-007",
        tenant_id=DEMO_TENANT.tenant_id,
        company_name="Gulf Coast Roofing LLC",
        address="4821 Westheimer Rd",
        city="Houston",
        state="TX",
        phone="+17135550042",
        email="info@gulfcoastroofing.com",
        website=None,
        rating=4.1,
        review_count=38,
        category="roofing contractor",
        score=82,
        status="contacted",
        last_contact_at=seven_days_ago,
        notes=(
            'CADENCE:{"first_contact_at":"'
            + seven_days_ago.isoformat()
            + '","last_step_completed":2}'
        ),
        created_at=seven_days_ago,
        updated_at=seven_days_ago,
    )

    _sub(f"Lead:           {stale_lead.company_name}")
    _sub(f"Status:         {stale_lead.status}")
    _sub(f"Last contact:   {stale_lead.last_contact_at.strftime('%Y-%m-%d')}")  # type: ignore[union-attr]
    _sub("Cadence step:   3 of 4  (day 7 — voice outreach)")
    print()

    result = call_prospect(stale_lead, DEMO_TENANT, dry_run=True)

    _sub("── Call script ──────────────────────────────────────────────────")
    _block(result.body, indent=4)
    print()

    stub_path = (
        BACKEND_DIR / "logs" / DEMO_TENANT.tenant_id / "calls" / "DRY_RUN_stub.mp3"
    )
    _sub(f"Audio stub:     {stub_path}")
    _sub(f"Word count:     {len(result.body.split())} words  (~{len(result.body.split()) // 2}s at 130 wpm)")
    _sub(f"Call result:    status={result.status} | channel={result.channel} | lead={result.lead_id}")

    report.calls_made = 1


def step_director_report(report: DailyReport) -> str:
    _step(6, 8, "DIRECTOR IA  —  COMPILE DAILY REPORT")

    top_line = (
        f"Top lead: {report.top_lead} (score {report.top_lead_score})"
        if report.top_lead
        else "No qualified leads found today."
    )

    rag_line = (
        "✓ live ChromaDB context injected into all emails"
        if report.rag_context_used
        else "✗ fallback template used (populate RAG collection to fix)"
    )

    summary = (
        f"*Daily Sales Report — {DEMO_TENANT.company_name}*\n"
        f"Date: {report.date}  |  Tenant: {report.tenant_id}\n"
        f"\n"
        f"• Leads scouted:    {report.leads_scouted}\n"
        f"• Leads qualified:  {report.leads_qualified}\n"
        f"• Emails sent:      {report.emails_sent}  [DRY_RUN]\n"
        f"• Calls made:       {report.calls_made}  [DRY_RUN — cadence day 7]\n"
        f"• Responses:        {report.responses}\n"
        f"• Meetings booked:  {report.meetings_booked}\n"
        f"• RAG:              {rag_line}\n"
        f"\n"
        f"• {top_line}\n"
        f"\n"
        f"Next run: tomorrow 7:00 AM {DEMO_TENANT.timezone}"
    )

    report.summary_text = summary

    _sub("DailyReport compiled:")
    print()
    _block(summary)
    return summary


def step_whatsapp(report: DailyReport) -> None:
    _step(7, 8, "WHATSAPP SUMMARY  →  owner notification (dry-run)")

    _sub(f"Recipient:  {DEMO_TENANT.owner_whatsapp}  ({DEMO_TENANT.owner_name})")
    print()
    _sub("── Message that would be delivered ─────────────────────────────")
    _block(report.summary_text, indent=4)
    print()

    result = send_whatsapp_summary(
        tenant_config=DEMO_TENANT,
        summary_text=report.summary_text,
        dry_run=True,
    )

    _sub(f"WhatsApp result:  status={result.status} | to={result.recipient}")
    _sub(
        "Voice escalation: armed — in production, Director waits 15 min for a\n"
        "                  read receipt; no reply → ElevenLabs voice call via Twilio."
    )


def step_cron_note() -> None:
    _step(8, 8, "PRODUCTION AUTOMATION NOTE")
    print()
    _block(
        "In production, this entire sequence runs automatically every day at\n"
        "7:00 AM tenant-local time via cron.py — no manual trigger needed.\n"
        "This script exists only to let you preview the output locally.\n"
        "\n"
        "scheduler/cron.py registers one APScheduler job per active tenant:\n"
        "  job_tenant_001  →  fires daily at 07:00 America/Chicago\n"
        "  job_tenant_002  →  fires daily at 07:00 America/Chicago\n"
        "  ...\n"
        "\n"
        "Each job calls director.run_daily(tenant_config), which orchestrates\n"
        "4 CrewAI tasks in order:\n"
        "  1. ProspectionManager  → Scout scrapes + qualifies leads\n"
        "  2. CloserManager       → EmailAgent runs day-0 cadence\n"
        "  3. PostSaleManager     → CallAgent handles day-7 follow-ups\n"
        "  4. Director IA         → compiles DailyReport, sends WhatsApp\n"
        "\n"
        "At 5:00 PM, end_of_day_sequence() checks for WhatsApp read receipts\n"
        "and escalates to an ElevenLabs voice call if the owner hasn't responded.",
        indent=2,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    _banner()

    report = DailyReport(
        tenant_id=DEMO_TENANT.tenant_id,
        date=datetime.utcnow().strftime("%Y-%m-%d"),
    )

    rag_context = step_rag_context(report)
    raw_leads   = step_scout(report)
    qualified   = step_filter(raw_leads, report)
    step_email_cadence(qualified, rag_context, report)
    step_call_cadence(report)
    step_director_report(report)
    step_whatsapp(report)
    step_cron_note()

    print()
    print("━" * W)
    print("  DAILY CYCLE COMPLETE")
    _sub(
        f"  {report.leads_scouted} scouted  →  {report.leads_qualified} qualified  "
        f"→  {report.emails_sent} emails  →  {report.calls_made} call  →  1 WhatsApp"
    )
    _sub("  RAG: live ChromaDB  |  Outbound: DRY_RUN only — nothing was sent")
    print("━" * W)
    print()


if __name__ == "__main__":
    main()
