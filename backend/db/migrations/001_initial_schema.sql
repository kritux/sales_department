-- 001_initial_schema.sql
-- Initial Supabase schema for JARVIS multi-tenant sales platform.
-- Run in Supabase SQL editor or via supabase db push.
-- All tables include tenant_id with RLS enforcing strict per-tenant isolation.

-- ============================================================
-- EXTENSIONS
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- ============================================================
-- TENANTS
-- ============================================================

CREATE TABLE IF NOT EXISTS tenants (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                   TEXT NOT NULL UNIQUE,           -- "tenant_001"
    company_name                TEXT NOT NULL,
    timezone                    TEXT NOT NULL DEFAULT 'America/Chicago',
    language                    TEXT NOT NULL DEFAULT 'en'
                                    CHECK (language IN ('es', 'en', 'both')),
    geo_center                  TEXT NOT NULL,                  -- "Houston, TX"
    geo_radius_miles            INTEGER NOT NULL DEFAULT 50,
    scraping_keywords           TEXT[] NOT NULL DEFAULT '{}',
    sender_name                 TEXT NOT NULL,
    sender_email                TEXT NOT NULL,
    owner_whatsapp              TEXT NOT NULL,
    owner_name                  TEXT NOT NULL,
    urgent_alert_threshold_usd  INTEGER NOT NULL DEFAULT 5000,
    -- lead_criteria stored as JSONB to mirror LeadCriteria Pydantic model
    lead_criteria               JSONB NOT NULL DEFAULT '{
        "min_rating": 3.5,
        "min_reviews": 10,
        "max_reviews": null,
        "has_website": null,
        "company_size": "any",
        "industries": [],
        "exclude_keywords": []
    }'::JSONB,
    active                      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tenants_tenant_id ON tenants (tenant_id);
CREATE INDEX idx_tenants_active    ON tenants (active);

-- ============================================================
-- LEADS
-- ============================================================

CREATE TABLE IF NOT EXISTS leads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    company_name    TEXT NOT NULL,
    address         TEXT NOT NULL DEFAULT '',
    city            TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT '',
    phone           TEXT,
    email           TEXT,
    website         TEXT,
    rating          NUMERIC(3, 1),
    review_count    INTEGER,
    category        TEXT NOT NULL DEFAULT '',
    score           INTEGER NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
    source          TEXT NOT NULL DEFAULT 'google_maps'
                        CHECK (source IN ('google_maps', 'yelp', 'manual')),
    status          TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN (
                            'new',
                            'contacted',
                            'responded',
                            'meeting_set',
                            'closed_won',
                            'closed_lost',
                            'no_response'
                        )),
    last_contact_at TIMESTAMPTZ,
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_leads_tenant_id        ON leads (tenant_id);
CREATE INDEX idx_leads_status           ON leads (tenant_id, status);
CREATE INDEX idx_leads_score            ON leads (tenant_id, score DESC);
CREATE INDEX idx_leads_last_contact_at  ON leads (tenant_id, last_contact_at);
CREATE INDEX idx_leads_created_at       ON leads (tenant_id, created_at DESC);

-- ============================================================
-- OUTBOUND_MESSAGES
-- ============================================================

CREATE TABLE IF NOT EXISTS outbound_messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    lead_id     UUID NOT NULL REFERENCES leads (id) ON DELETE CASCADE,
    channel     TEXT NOT NULL
                    CHECK (channel IN ('email', 'whatsapp', 'voice')),
    recipient   TEXT NOT NULL,          -- email address or E.164 phone number
    subject     TEXT,                   -- email only, NULL for voice/whatsapp
    body        TEXT NOT NULL,
    sent_at     TIMESTAMPTZ,            -- NULL when dry_run = TRUE
    status      TEXT NOT NULL DEFAULT 'dry_run'
                    CHECK (status IN ('sent', 'failed', 'dry_run')),
    dry_run     BOOLEAN NOT NULL DEFAULT TRUE,
    message_id  TEXT,                   -- provider-assigned ID for receipt tracking
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_outbound_messages_tenant_id  ON outbound_messages (tenant_id);
CREATE INDEX idx_outbound_messages_lead_id    ON outbound_messages (lead_id);
CREATE INDEX idx_outbound_messages_sent_at    ON outbound_messages (tenant_id, sent_at);
CREATE INDEX idx_outbound_messages_channel    ON outbound_messages (tenant_id, channel);
CREATE INDEX idx_outbound_messages_status     ON outbound_messages (tenant_id, status);

-- ============================================================
-- DAILY_REPORTS
-- ============================================================

CREATE TABLE IF NOT EXISTS daily_reports (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    report_date             DATE NOT NULL,
    leads_scraped           INTEGER NOT NULL DEFAULT 0,
    leads_qualified         INTEGER NOT NULL DEFAULT 0,
    emails_sent             INTEGER NOT NULL DEFAULT 0,
    calls_made              INTEGER NOT NULL DEFAULT 0,
    responses_received      INTEGER NOT NULL DEFAULT 0,
    meetings_booked         INTEGER NOT NULL DEFAULT 0,
    pipeline_value_usd      NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    urgent_alerts_sent      INTEGER NOT NULL DEFAULT 0,
    -- agent_activity stores List[AgentActivity] from DailyReport contract
    agent_activity          JSONB NOT NULL DEFAULT '[]'::JSONB,
    -- top_leads stores List[str] of lead UUIDs worth reviewing
    top_leads               TEXT[] NOT NULL DEFAULT '{}',
    summary_text            TEXT NOT NULL DEFAULT '',
    whatsapp_sent           BOOLEAN NOT NULL DEFAULT FALSE,
    call_made               BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (tenant_id, report_date)
);

CREATE INDEX idx_daily_reports_tenant_id    ON daily_reports (tenant_id);
CREATE INDEX idx_daily_reports_report_date  ON daily_reports (tenant_id, report_date DESC);

-- ============================================================
-- UPDATED_AT TRIGGER (shared function)
-- ============================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_daily_reports_updated_at
    BEFORE UPDATE ON daily_reports
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE tenants           ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads             ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbound_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_reports     ENABLE ROW LEVEL SECURITY;

-- ------------------------------------------------------------
-- TENANTS RLS
-- Authenticated users may only see/modify their own tenant row.
-- The tenant_id in the JWT claim must match.
-- Service role bypasses RLS for backend operations.
-- ------------------------------------------------------------

CREATE POLICY tenants_select ON tenants
    FOR SELECT TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY tenants_insert ON tenants
    FOR INSERT TO authenticated
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY tenants_update ON tenants
    FOR UPDATE TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'))
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY tenants_delete ON tenants
    FOR DELETE TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'));

-- ------------------------------------------------------------
-- LEADS RLS
-- ------------------------------------------------------------

CREATE POLICY leads_select ON leads
    FOR SELECT TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY leads_insert ON leads
    FOR INSERT TO authenticated
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY leads_update ON leads
    FOR UPDATE TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'))
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY leads_delete ON leads
    FOR DELETE TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'));

-- ------------------------------------------------------------
-- OUTBOUND_MESSAGES RLS
-- ------------------------------------------------------------

CREATE POLICY outbound_messages_select ON outbound_messages
    FOR SELECT TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY outbound_messages_insert ON outbound_messages
    FOR INSERT TO authenticated
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY outbound_messages_update ON outbound_messages
    FOR UPDATE TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'))
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

-- Comms logs are never hard-deleted; archive instead.
-- No DELETE policy for outbound_messages.

-- ------------------------------------------------------------
-- DAILY_REPORTS RLS
-- ------------------------------------------------------------

CREATE POLICY daily_reports_select ON daily_reports
    FOR SELECT TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY daily_reports_insert ON daily_reports
    FOR INSERT TO authenticated
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY daily_reports_update ON daily_reports
    FOR UPDATE TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'))
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

-- Reports are never deleted; no DELETE policy.

-- ============================================================
-- COMMENTS
-- ============================================================

COMMENT ON TABLE tenants IS
    'One row per client. Source of truth for TenantConfig loaded by every agent.';

COMMENT ON TABLE leads IS
    'Leads discovered by Scout. Comms updates status. Director reads for reporting.';

COMMENT ON TABLE outbound_messages IS
    'Immutable log of every email/WhatsApp/voice action. Comms writes, Director reads.';

COMMENT ON TABLE daily_reports IS
    'One row per tenant per calendar day. Director writes at end-of-day sequence.';

COMMENT ON COLUMN tenants.lead_criteria IS
    'Serialized LeadCriteria Pydantic model (backend/config/tenants.py).';

COMMENT ON COLUMN daily_reports.agent_activity IS
    'Serialized List[AgentActivity] from DailyReport contract (backend/api/reports.py).';

COMMENT ON COLUMN outbound_messages.sent_at IS
    'NULL when dry_run=TRUE. Always set to actual send timestamp in production.';
