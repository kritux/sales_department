"""
APScheduler setup — one timezone-aware cron job per active tenant.

Each active tenant gets a job named ``job_{tenant_id}`` that fires at
07:00 tenant local time every day. Jobs are registered on a single
BackgroundScheduler instance that is started once at application boot.

Design notes:
  - Uses CronTrigger with the tenant's IANA timezone so DST is handled
    automatically by APScheduler / pytz.
  - `run_daily` is imported lazily inside each job callable to avoid
    a hard dependency at module load time (keeps tests fast).
  - Scheduler is a module-level singleton; call start_scheduler() once
    from FastAPI's startup event.
  - Idempotent: if a job already exists for a tenant, it is replaced
    so re-registering on config reload is safe.

Public API:
    start_scheduler(tenants=None)          -> BackgroundScheduler
    stop_scheduler()                       -> None
    register_tenant_job(scheduler, tenant) -> None
    get_scheduler()                        -> BackgroundScheduler | None
"""

import logging
from typing import List, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config.tenants import TenantConfig

logger = logging.getLogger(__name__)

_DAILY_HOUR = 7
_DAILY_MINUTE = 0

_scheduler: Optional[BackgroundScheduler] = None


# ---------------------------------------------------------------------------
# Job callable
# ---------------------------------------------------------------------------

def _make_job(tenant_config: TenantConfig):
    """Return a zero-arg callable that runs run_daily for this tenant."""

    def _run():
        from agents.director import run_daily  # lazy — avoids circular dep

        logger.info(
            "cron trigger | tenant=%s | starting run_daily",
            tenant_config.tenant_id,
        )
        try:
            result = run_daily(tenant_config)
            logger.info(
                "cron trigger | tenant=%s | run_daily complete | chars=%d",
                tenant_config.tenant_id,
                len(result),
            )
        except Exception as exc:
            logger.error(
                "cron trigger | tenant=%s | run_daily FAILED | error=%s",
                tenant_config.tenant_id,
                exc,
            )

    return _run


# ---------------------------------------------------------------------------
# Per-tenant job registration
# ---------------------------------------------------------------------------

def register_tenant_job(
    scheduler: BackgroundScheduler,
    tenant_config: TenantConfig,
) -> None:
    """
    Register (or replace) a daily 7am cron job for a single tenant.

    The job fires at 07:00 in the tenant's local timezone every day.
    If a job with the same id already exists it is replaced, making
    this call idempotent.

    Args:
        scheduler:     Running BackgroundScheduler instance.
        tenant_config: TenantConfig for the tenant to schedule.
    """
    tz = pytz.timezone(tenant_config.timezone)
    job_id = f"job_{tenant_config.tenant_id}"

    trigger = CronTrigger(
        hour=_DAILY_HOUR,
        minute=_DAILY_MINUTE,
        timezone=tz,
    )

    scheduler.add_job(
        _make_job(tenant_config),
        trigger=trigger,
        id=job_id,
        name=f"Daily run — {tenant_config.company_name}",
        replace_existing=True,
    )

    logger.info(
        "Registered job | id=%s | timezone=%s | fires_at=%02d:%02d local",
        job_id,
        tenant_config.timezone,
        _DAILY_HOUR,
        _DAILY_MINUTE,
    )


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler(
    tenants: Optional[List[TenantConfig]] = None,
) -> BackgroundScheduler:
    """
    Create, populate, and start the global BackgroundScheduler.

    Loads all active tenants from Supabase (via get_all_active_tenants)
    unless a list is passed directly (useful for tests / seeding).

    Args:
        tenants: Override list of tenants to schedule. If None, loads
                 from Supabase via get_all_active_tenants().

    Returns:
        The started BackgroundScheduler instance.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("start_scheduler called while scheduler already running — ignoring")
        return _scheduler

    _scheduler = BackgroundScheduler()

    if tenants is None:
        from config.tenants import get_all_active_tenants  # lazy
        tenants = get_all_active_tenants()

    for tc in tenants:
        if tc.active:
            register_tenant_job(_scheduler, tc)

    _scheduler.start()
    logger.info("Scheduler started | jobs=%d", len(_scheduler.get_jobs()))
    return _scheduler


def stop_scheduler() -> None:
    """Gracefully shut down the global scheduler if it is running."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None


def get_scheduler() -> Optional[BackgroundScheduler]:
    """Return the global scheduler instance (None if not started)."""
    return _scheduler
