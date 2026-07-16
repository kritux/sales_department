#!/usr/bin/env python3
"""
BIZON — Command Center | Local Demo
Run the full daily sales pipeline for Growth Bizon without Supabase or any
external API calls. DRY_RUN throughout — nothing is sent, nothing is written.

Run from the backend/ directory:
    python run_local_demo.py
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# ── path + env setup ─────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
REPO_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

# Force DRY_RUN before settings are imported so every tool sees it.
os.environ["DRY_RUN"] = "true"

# ── project imports ───────────────────────────────────────────────────────────
from config.tenants import TenantConfig, LeadCriteria   # noqa: E402
from db.models import Lead                               # noqa: E402
from tools.maps_scraper import scrape_google_maps        # noqa: E402
from tools.lead_filter import filter_leads, score_lead, SCORE_FLOOR  # noqa: E402
from tools.rag_loader import load_docs                   # noqa: E402
from tools.rag_query import query_rag                    # noqa: E402
from tools.email_tool import render_email                # noqa: E402
from tools.whatsapp_tool import send_whatsapp_summary    # noqa: E402

# ── display helpers ───────────────────────────────────────────────────────────
W = 64


def _banner() -> None:
    inner = W - 2
    print()
    print("╔" + "═" * inner + "╗")
    print("║" + "  BIZON — Command Center  |  LOCAL DEMO".center(inner) + "║")
    print("║" + "  Growth Bizon Sales AI  |  DRY_RUN MODE".center(inner) + "║")
    print("╚" + "═" * inner + "╝")
    print()
    print(f"  Started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  DRY_RUN=true — no external calls, no DB writes")


def _step(n: int, total: int, title: str) -> None:
    print()
    print("━" * W)
    print(f"  STEP {n}/{total}  ·  {title}")
    print("━" * W)


def _sub(text: str) -> None:
    print(f"  {text}")


def _block(text: str, indent: int = 6) -> None:
    pad = " " * indent
    for line in text.splitlines():
        print(pad + line)


def _hr() -> None:
    print("  " + "─" * (W - 4))


# ── demo tenant (no Supabase) ─────────────────────────────────────────────────
DEMO_TENANT = TenantConfig(
    tenant_id="tenant_001",
    company_name="Growth Bizon",
    timezone="America/Chicago",
    language="en",
    geo_center="Houston, TX",
    geo_radius_miles=50,
    scraping_keywords=[
        "contractor no website Houston",
        "plumber no website TX",
    ],
    lead_criteria=LeadCriteria(
        industries=["contractor", "plumber", "general contractor"],
        exclude_keywords=["chain", "franchise"],
        min_rating=3.5,
        min_reviews=5,
    ),
    sender_name="Carlos Rodríguez",
    sender_email="carlos@growthbizon.com",
    owner_whatsapp="+15551234567",
    owner_name="Carlos",
    rag_collection="rag_tenant_001",
    urgent_alert_threshold_usd=5000,
)

KB_PATH = REPO_DIR / "knowledge_base" / "growth_bizon"

# ── pipeline ──────────────────────────────────────────────────────────────────


def step_scout() -> List[dict]:
    _step(1, 5, "SCOUT — Finding Leads")
    _sub(f"Tenant:    {DEMO_TENANT.tenant_id} ({DEMO_TENANT.company_name})")
    _sub(f"Geo:       {DEMO_TENANT.geo_center}, radius {DEMO_TENANT.geo_radius_miles} mi")
    _sub(f"Keywords:  {DEMO_TENANT.scraping_keywords}")
    print()

    all_raw: List[dict] = []
    for kw in DEMO_TENANT.scraping_keywords:
        _sub(f'→ Scraping: "{kw}"')
        raw = scrape_google_maps(
            query=kw,
            limit=5,
            tenant_id=DEMO_TENANT.tenant_id,
            dry_run=True,
        )
        all_raw.extend(raw)
        _sub(f"  {len(raw)} raw leads returned")
        print()

    _sub(f"Total raw leads collected: {len(all_raw)}")
    return all_raw


def step_filter(all_raw: List[dict]) -> List[Lead]:
    _step(2, 5, "FILTER — Scoring & Qualifying")
    _sub(f"Industries: {DEMO_TENANT.lead_criteria.industries}")
    _sub(f"Exclude:    {DEMO_TENANT.lead_criteria.exclude_keywords}")
    _sub(f"Score floor (must exceed): {SCORE_FLOOR}")
    print()

    for raw in all_raw:
        s = score_lead(raw, DEMO_TENANT.lead_criteria)
        flag = "✓ QUALIFIED" if s > SCORE_FLOOR else "✗ disqualified"
        _sub(f"  {raw['company_name']:<38}  score={s:>3}   {flag}")

    qualified = filter_leads(
        raw_leads=all_raw,
        criteria=DEMO_TENANT.lead_criteria,
        tenant_id=DEMO_TENANT.tenant_id,
    )
    print()
    _sub(f"Qualified leads: {len(qualified)} / {len(all_raw)}  (sorted by score DESC)")
    return qualified


def step_rag() -> str:
    _step(3, 5, "RAG — Knowledge Base")
    rag_context = ""

    if not KB_PATH.exists():
        _sub(f"Knowledge base not found at: {KB_PATH}")
        _sub("Skipping — email template will use built-in fallback copy")
        return rag_context

    _sub(f"Path: {KB_PATH}")
    print()

    # Load docs (dry-run — no ChromaDB writes)
    _sub("Loading docs (dry-run — no ChromaDB writes):")
    print()
    try:
        load_result = load_docs(
            tenant_id=DEMO_TENANT.tenant_id,
            docs_path=str(KB_PATH),
            dry_run=True,
        )
        print()
        _sub(
            f"  files_processed={load_result['files_processed']}  "
            f"would-load chunks={load_result.get('dry_run_chunks', 0)}"
        )
    except Exception as exc:
        _sub(f"  load_docs error: {exc}")

    # Query RAG — gracefully degrades if chromadb not installed
    print()
    _sub("Querying RAG for email context (top-5 chunks):")
    print()
    try:
        rag_resp = query_rag(
            tenant_id=DEMO_TENANT.tenant_id,
            query="services pricing General Contractor Houston small business",
        )
        print()
        if rag_resp.found:
            rag_context = rag_resp.context
            _sub(
                f"  found=True | chunks={len(rag_resp.chunks)} | "
                f"top_score={rag_resp.chunks[0].relevance_score:.4f}"
            )
            _sub("  Context snippet (first 300 chars):")
            _block(rag_context[:300] + ("…" if len(rag_context) > 300 else ""))
        else:
            _sub("  found=False — ChromaDB not installed or collection not loaded yet")
            _sub("  Email template will use built-in Growth Bizon fallback copy")
    except Exception as exc:
        _sub(f"  query_rag error: {exc}")
        _sub("  Email template will use built-in fallback copy")

    return rag_context


def step_emails(qualified: List[Lead], rag_context: str) -> List[Dict]:
    _step(4, 5, "EMAIL DRAFTS — Outreach")

    if not qualified:
        _sub("No qualified leads — nothing to draft")
        return []

    _sub(f"Drafting personalized cold emails for {len(qualified)} lead(s)...")
    _sub(f"RAG context available: {'yes' if rag_context else 'no (fallback copy)'}")

    drafts: List[Dict] = []
    for i, lead in enumerate(qualified, 1):
        print()
        _hr()
        _sub(f"Lead {i}/{len(qualified)}: {lead.company_name}")
        _sub(f"  ID={lead.id[:8]}…  score={lead.score}  "
             f"category={lead.category}  city={lead.city}")
        _sub(f"  phone={lead.phone or 'n/a'}  "
             f"email={lead.email or '(none — send skipped in real run)'}")
        print()

        subject, body = render_email(lead, DEMO_TENANT, rag_context)
        drafts.append({"lead": lead, "subject": subject, "body": body})

        _sub(f"  SUBJECT: {subject}")
        print()
        _sub("  BODY:")
        _block(body)

    print()
    _hr()
    _sub(f"Drafts generated: {len(drafts)}")
    _sub("(send_email skipped — leads have no email address in dry-run stubs)")
    return drafts


def step_report(all_raw: List[dict], qualified: List[Lead], drafts: List[Dict]) -> None:
    _step(5, 5, "DIRECTOR REPORT + WHATSAPP SUMMARY")

    now_str = datetime.utcnow().strftime("%Y-%m-%d")
    top_line = (
        f"Top lead today: {qualified[0].company_name} (score {qualified[0].score})"
        if qualified else "No qualified leads found today."
    )

    summary = (
        f"*Daily Sales Report — {DEMO_TENANT.company_name}*\n"
        f"Date: {now_str}  |  Tenant: {DEMO_TENANT.tenant_id}\n"
        f"\n"
        f"• Leads scouted:      {len(all_raw)}\n"
        f"• Leads qualified:    {len(qualified)}\n"
        f"• Emails drafted:     {len(drafts)}\n"
        f"• Emails sent:        0  (DRY_RUN — stubs have no email address)\n"
        f"• Meetings booked:    0\n"
        f"• Follow-ups queued:  0\n"
        f"\n"
        f"• {top_line}\n"
        f"\n"
        f"Next run: tomorrow 7:00 AM {DEMO_TENANT.timezone}"
    )

    _sub("Compiled DailyReport:")
    print()
    _block(summary)
    print()

    _sub("Dispatching WhatsApp summary (dry-run):")
    print()

    wa_result = send_whatsapp_summary(
        tenant_config=DEMO_TENANT,
        summary_text=summary,
        dry_run=True,
    )

    print()
    _sub(f"WhatsApp result:  status={wa_result.status} | to={wa_result.recipient}")
    _sub(
        "Voice escalation: skipped — WhatsApp status is 'dry_run', not 'sent', "
        "so no SID to check"
    )


def main() -> None:
    _banner()

    all_raw   = step_scout()
    qualified = step_filter(all_raw)
    rag_ctx   = step_rag()
    drafts    = step_emails(qualified, rag_ctx)
    step_report(all_raw, qualified, drafts)

    print()
    print("━" * W)
    print("  DEMO COMPLETE")
    _sub(
        f"  {len(all_raw)} leads scouted  →  {len(qualified)} qualified  "
        f"→  {len(drafts)} emails drafted  →  1 WhatsApp logged"
    )
    _sub("  Full pipeline ran end-to-end in DRY_RUN mode. No external calls made.")
    print("━" * W)
    print()


if __name__ == "__main__":
    main()
