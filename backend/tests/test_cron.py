"""
Tests for backend/scheduler/cron.py.

APScheduler and pytz are real imports — they're lightweight and
already installed. The director.run_daily import is lazy (inside
_make_job), so it is patched at call time rather than module load.

Mock strategy:
  - BackgroundScheduler: mocked via patch in each test to avoid
    actually starting threads
  - run_daily: patched inside _run() closures via the module path
    agents.director.run_daily when testing the job callable directly

Coverage:
  - register_tenant_job: job id, trigger timezone, replace_existing
  - CronTrigger UTC offset: 7am America/Chicago = 13:00 UTC (CST, UTC-6)
  - start_scheduler: registers only active tenants, starts scheduler
  - stop_scheduler: calls shutdown, clears global
  - get_scheduler: returns current global
  - _make_job callable: calls run_daily, logs errors without raising
  - Idempotency: registering same tenant twice uses replace_existing=True
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytz
import pytest
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Remove any mock scheduler entries injected by other test files (e.g. test_director.py
# injects sys.modules["scheduler"] = MagicMock() which would shadow the real package).
for _key in list(sys.modules.keys()):
    if _key == "scheduler" or _key.startswith("scheduler."):
        del sys.modules[_key]

from config.tenants import TenantConfig, LeadCriteria  # noqa: E402
import scheduler.cron as cron_module  # noqa: E402
from scheduler.cron import (  # noqa: E402
    register_tenant_job,
    start_scheduler,
    stop_scheduler,
    get_scheduler,
    _make_job,
    _DAILY_HOUR,
    _DAILY_MINUTE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(**kwargs) -> TenantConfig:
    defaults = dict(
        tenant_id="tenant_001",
        company_name="Growth Bizon",
        timezone="America/Chicago",
        language="en",
        geo_center="Houston, TX",
        scraping_keywords=["contractor Houston"],
        lead_criteria=LeadCriteria(industries=["contractor"]),
        sender_name="Sales Team",
        sender_email="sales@growthbizon.com",
        owner_whatsapp="+15551234567",
        owner_name="Carlos",
        rag_collection="rag_tenant_001",
    )
    defaults.update(kwargs)
    return TenantConfig(**defaults)


@pytest.fixture(autouse=True)
def reset_global_scheduler():
    """Ensure the module-level _scheduler is None before and after each test."""
    cron_module._scheduler = None
    yield
    cron_module._scheduler = None


# ---------------------------------------------------------------------------
# register_tenant_job
# ---------------------------------------------------------------------------

class TestRegisterTenantJob:
    def setup_method(self):
        self.tenant = _make_tenant()
        self.mock_scheduler = MagicMock()

    def test_add_job_called(self):
        register_tenant_job(self.mock_scheduler, self.tenant)
        self.mock_scheduler.add_job.assert_called_once()

    def test_job_id_is_job_tenant_id(self):
        register_tenant_job(self.mock_scheduler, self.tenant)
        _, kwargs = self.mock_scheduler.add_job.call_args
        assert kwargs["id"] == "job_tenant_001"

    def test_replace_existing_true(self):
        register_tenant_job(self.mock_scheduler, self.tenant)
        _, kwargs = self.mock_scheduler.add_job.call_args
        assert kwargs["replace_existing"] is True

    def test_trigger_is_cron_trigger(self):
        register_tenant_job(self.mock_scheduler, self.tenant)
        _, kwargs = self.mock_scheduler.add_job.call_args
        assert isinstance(kwargs["trigger"], CronTrigger)

    def test_trigger_timezone_matches_tenant(self):
        register_tenant_job(self.mock_scheduler, self.tenant)
        _, kwargs = self.mock_scheduler.add_job.call_args
        trigger = kwargs["trigger"]
        tz = trigger.timezone
        assert str(tz) == "America/Chicago"

    def test_job_name_mentions_company(self):
        register_tenant_job(self.mock_scheduler, self.tenant)
        _, kwargs = self.mock_scheduler.add_job.call_args
        assert "Growth Bizon" in kwargs["name"]

    def test_job_callable_is_callable(self):
        register_tenant_job(self.mock_scheduler, self.tenant)
        args, _ = self.mock_scheduler.add_job.call_args
        assert callable(args[0])

    def test_different_tenants_get_different_job_ids(self):
        tenant_b = _make_tenant(tenant_id="tenant_002", company_name="Corp B")
        scheduler_b = MagicMock()
        register_tenant_job(self.mock_scheduler, self.tenant)
        register_tenant_job(scheduler_b, tenant_b)

        _, kwargs_a = self.mock_scheduler.add_job.call_args
        _, kwargs_b = scheduler_b.add_job.call_args
        assert kwargs_a["id"] != kwargs_b["id"]

    def test_idempotent_replace_existing(self):
        """Calling twice doesn't error — replace_existing=True handles it."""
        register_tenant_job(self.mock_scheduler, self.tenant)
        register_tenant_job(self.mock_scheduler, self.tenant)
        assert self.mock_scheduler.add_job.call_count == 2
        for c in self.mock_scheduler.add_job.call_args_list:
            _, kwargs = c
            assert kwargs["replace_existing"] is True


# ---------------------------------------------------------------------------
# UTC trigger time — America/Chicago key test
# ---------------------------------------------------------------------------

class TestChicagoUTCOffset:
    """
    Verify that a job registered for America/Chicago fires at 13:00 UTC
    during CST (UTC-6, November–March) and 12:00 UTC during CDT (UTC-5).

    We use a real CronTrigger and ask APScheduler for the next fire time
    from a known reference moment in CST (winter time).
    """

    def test_chicago_cst_fires_at_13_utc(self):
        """7am CST = 13:00 UTC (UTC-6, standard time)."""
        tz_chicago = pytz.timezone("America/Chicago")
        trigger = CronTrigger(hour=_DAILY_HOUR, minute=_DAILY_MINUTE, timezone=tz_chicago)

        # Reference: Monday 06 Jan 2025 06:00:00 CST (just before 7am)
        # UTC = 12:00:00 on same day (CST = UTC-6)
        ref_cst = tz_chicago.localize(datetime(2025, 1, 6, 6, 0, 0))

        next_fire = trigger.get_next_fire_time(None, ref_cst)
        assert next_fire is not None
        utc_next = next_fire.astimezone(pytz.utc)
        assert utc_next.hour == 13
        assert utc_next.minute == 0

    def test_chicago_cdt_fires_at_12_utc(self):
        """7am CDT = 12:00 UTC (UTC-5, daylight saving time)."""
        tz_chicago = pytz.timezone("America/Chicago")
        trigger = CronTrigger(hour=_DAILY_HOUR, minute=_DAILY_MINUTE, timezone=tz_chicago)

        # Reference: Monday 07 Jul 2025 06:00:00 CDT (just before 7am in summer)
        # UTC = 11:00:00 (CDT = UTC-5)
        ref_cdt = tz_chicago.localize(datetime(2025, 7, 7, 6, 0, 0))

        next_fire = trigger.get_next_fire_time(None, ref_cdt)
        assert next_fire is not None
        utc_next = next_fire.astimezone(pytz.utc)
        assert utc_next.hour == 12
        assert utc_next.minute == 0

    def test_register_job_uses_correct_timezone_object(self):
        mock_sched = MagicMock()
        tenant = _make_tenant(timezone="America/Chicago")
        register_tenant_job(mock_sched, tenant)
        _, kwargs = mock_sched.add_job.call_args
        trigger: CronTrigger = kwargs["trigger"]
        # Verify the timezone on the trigger resolves to Chicago
        tz_chicago = pytz.timezone("America/Chicago")
        assert trigger.timezone == tz_chicago


# ---------------------------------------------------------------------------
# start_scheduler
# ---------------------------------------------------------------------------

class TestStartScheduler:
    # Use patch.object(cron_module, ...) instead of patch("scheduler.cron....")
    # because sys.modules["scheduler"] may be a MagicMock (injected by
    # test_director.py's autouse), which causes __import__("scheduler.cron")
    # to resolve to mock.cron rather than the real module.

    def test_returns_scheduler(self):
        tenants = [_make_tenant()]
        with patch.object(cron_module, "BackgroundScheduler") as MockSched:
            result = start_scheduler(tenants=tenants)
        assert result is MockSched.return_value

    def test_scheduler_started(self):
        tenants = [_make_tenant()]
        with patch.object(cron_module, "BackgroundScheduler") as MockSched:
            start_scheduler(tenants=tenants)
        MockSched.return_value.start.assert_called_once()

    def test_registers_job_for_each_active_tenant(self):
        tenants = [
            _make_tenant(tenant_id="tenant_001"),
            _make_tenant(tenant_id="tenant_002", company_name="Corp B"),
        ]
        with patch.object(cron_module, "BackgroundScheduler") as MockSched:
            start_scheduler(tenants=tenants)
        assert MockSched.return_value.add_job.call_count == 2

    def test_skips_inactive_tenants(self):
        tenants = [
            _make_tenant(tenant_id="tenant_001", active=True),
            _make_tenant(tenant_id="tenant_002", company_name="Inactive", active=False),
        ]
        with patch.object(cron_module, "BackgroundScheduler") as MockSched:
            start_scheduler(tenants=tenants)
        assert MockSched.return_value.add_job.call_count == 1

    def test_sets_global_scheduler(self):
        tenants = [_make_tenant()]
        with patch.object(cron_module, "BackgroundScheduler") as MockSched:
            start_scheduler(tenants=tenants)
        assert cron_module._scheduler is MockSched.return_value

    def test_no_tenants_starts_empty_scheduler(self):
        with patch.object(cron_module, "BackgroundScheduler") as MockSched:
            start_scheduler(tenants=[])
        MockSched.return_value.add_job.assert_not_called()
        MockSched.return_value.start.assert_called_once()

    def test_already_running_returns_existing(self):
        mock_existing = MagicMock()
        mock_existing.running = True
        cron_module._scheduler = mock_existing
        with patch.object(cron_module, "BackgroundScheduler") as MockSched:
            result = start_scheduler(tenants=[])
        assert result is mock_existing
        MockSched.assert_not_called()

    def test_loads_tenants_from_supabase_when_none_passed(self):
        fake_tenants = [_make_tenant()]
        with patch.object(cron_module, "BackgroundScheduler"), \
             patch("config.tenants.get_all_active_tenants", return_value=fake_tenants) as mock_load:
            start_scheduler()
        mock_load.assert_called_once()


# ---------------------------------------------------------------------------
# stop_scheduler
# ---------------------------------------------------------------------------

class TestStopScheduler:
    def test_calls_shutdown(self):
        mock_sched = MagicMock()
        mock_sched.running = True
        cron_module._scheduler = mock_sched
        stop_scheduler()
        mock_sched.shutdown.assert_called_once_with(wait=False)

    def test_clears_global_scheduler(self):
        mock_sched = MagicMock()
        mock_sched.running = True
        cron_module._scheduler = mock_sched
        stop_scheduler()
        assert cron_module._scheduler is None

    def test_no_error_when_not_running(self):
        cron_module._scheduler = None
        stop_scheduler()  # must not raise

    def test_no_shutdown_when_not_running(self):
        mock_sched = MagicMock()
        mock_sched.running = False
        cron_module._scheduler = mock_sched
        stop_scheduler()
        mock_sched.shutdown.assert_not_called()


# ---------------------------------------------------------------------------
# get_scheduler
# ---------------------------------------------------------------------------

class TestGetScheduler:
    def test_returns_none_before_start(self):
        assert get_scheduler() is None

    def test_returns_scheduler_after_start(self):
        mock_sched = MagicMock()
        cron_module._scheduler = mock_sched
        assert get_scheduler() is mock_sched


# ---------------------------------------------------------------------------
# _make_job callable
# ---------------------------------------------------------------------------

class TestMakeJob:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_returns_callable(self):
        job = _make_job(self.tenant)
        assert callable(job)

    def test_calls_run_daily_with_tenant(self):
        job = _make_job(self.tenant)
        with patch("agents.director.run_daily", return_value="result") as mock_run:
            job()
        mock_run.assert_called_once_with(self.tenant)

    def test_does_not_raise_on_run_daily_error(self):
        job = _make_job(self.tenant)
        with patch("agents.director.run_daily", side_effect=RuntimeError("boom")):
            job()  # must not propagate exception

    def test_different_tenants_produce_independent_jobs(self):
        tenant_b = _make_tenant(tenant_id="tenant_002", company_name="Corp B")
        job_a = _make_job(self.tenant)
        job_b = _make_job(tenant_b)

        calls = []
        def capture_run(tc):
            calls.append(tc.tenant_id)
            return "ok"

        with patch("agents.director.run_daily", side_effect=capture_run):
            job_a()
            job_b()

        assert calls == ["tenant_001", "tenant_002"]
