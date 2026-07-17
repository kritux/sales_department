"""
Daily report endpoints.

Routes:
    GET /reports/{tenant_id}/daily    — today's report (or ?date=YYYY-MM-DD)
    GET /reports/{tenant_id}/history  — paginated report history

Owns Contract 4 — DailyReport (TEAM.md).

Auth:
    All routes require Authorization: Bearer <token>.

Phase 1–4: Supabase is not wired. Endpoints return 503.
    Phase 5 replaces stubs with Supabase queries on the daily_reports table.
"""

import logging
from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


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
# Contract 4 — DailyReport models (TEAM.md)
# ---------------------------------------------------------------------------


class AgentActivity(BaseModel):
    agent_name: str
    tasks_completed: int
    tasks_failed: int
    tokens_used: int
    cost_usd: float


class DailyReport(BaseModel):
    tenant_id: str
    report_date: date
    leads_scraped: int
    leads_qualified: int
    emails_sent: int
    calls_made: int
    responses_received: int
    meetings_booked: int
    pipeline_value_usd: float
    urgent_alerts_sent: int
    agent_activity: List[AgentActivity]
    top_leads: List[str]
    summary_text: str
    whatsapp_sent: bool
    call_made: bool


# ---------------------------------------------------------------------------
# Supabase stubs (patchable in tests)
# ---------------------------------------------------------------------------


def _fetch_daily_report(tenant_id: str, report_date: date) -> DailyReport:
    raise HTTPException(
        status_code=503,
        detail=(
            f"Report fetch requires Supabase integration (Phase 5). "
            f"tenant_id={tenant_id!r} date={report_date}"
        ),
    )


def _fetch_report_history(
    tenant_id: str, limit: int, offset: int
) -> List[DailyReport]:
    raise HTTPException(
        status_code=503,
        detail=f"Report history requires Supabase integration (Phase 5). tenant_id={tenant_id!r}",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{tenant_id}/daily", response_model=DailyReport)
def get_daily_report(
    tenant_id: str,
    report_date: Optional[date] = Query(
        default=None,
        description="ISO date (YYYY-MM-DD). Defaults to today.",
    ),
    token: str = Depends(_require_auth),
) -> DailyReport:
    """
    Fetch the daily report for a tenant.

    Defaults to today's date. Pass ?date=YYYY-MM-DD for historical reports.
    """
    target = report_date or date.today()
    logger.info("GET /reports/%s/daily | date=%s", tenant_id, target)
    return _fetch_daily_report(tenant_id, target)


@router.get("/{tenant_id}/history", response_model=List[DailyReport])
def get_report_history(
    tenant_id: str,
    limit: int = Query(default=30, ge=1, le=90),
    offset: int = Query(default=0, ge=0),
    token: str = Depends(_require_auth),
) -> List[DailyReport]:
    """
    Paginated history of daily reports for a tenant.

    Sorted newest-first. Max 90 per page.
    """
    logger.info(
        "GET /reports/%s/history | limit=%d | offset=%d",
        tenant_id, limit, offset,
    )
    return _fetch_report_history(tenant_id, limit, offset)
