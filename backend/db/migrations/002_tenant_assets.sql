-- 002_tenant_assets.sql
-- Per-tenant brand assets: logos, icon, color/font config.
-- Run after 001_initial_schema.sql in Supabase SQL editor or supabase db push.

-- ============================================================
-- TENANT_ASSETS
-- ============================================================

CREATE TABLE IF NOT EXISTS tenant_assets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    asset_type  TEXT NOT NULL
                    CHECK (asset_type IN (
                        'logo_light',        -- light-background logo (PNG/SVG)
                        'logo_dark',         -- dark-background / reversed logo
                        'icon',              -- square app icon / favicon
                        'brand_colors_json', -- JSON string: {"primary":"#0295fd",...}
                        'brand_fonts_json'   -- JSON string: {"header":"Poppins",...}
                    )),
    file_url    TEXT NOT NULL,          -- Supabase Storage path or full URL for JSON assets
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Exactly one asset per type per tenant; UPSERT on (tenant_id, asset_type)
    UNIQUE (tenant_id, asset_type)
);

CREATE INDEX idx_tenant_assets_tenant_id ON tenant_assets (tenant_id);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE tenant_assets ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_assets_select ON tenant_assets
    FOR SELECT TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY tenant_assets_insert ON tenant_assets
    FOR INSERT TO authenticated
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY tenant_assets_update ON tenant_assets
    FOR UPDATE TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'))
    WITH CHECK (tenant_id = (auth.jwt() ->> 'tenant_id'));

CREATE POLICY tenant_assets_delete ON tenant_assets
    FOR DELETE TO authenticated
    USING (tenant_id = (auth.jwt() ->> 'tenant_id'));

-- ============================================================
-- UPDATED_AT TRIGGER
-- ============================================================

-- tenant_assets.uploaded_at acts as the timestamp — no separate updated_at needed.
-- set_updated_at() function is already defined in 001_initial_schema.sql.

-- ============================================================
-- COMMENTS
-- ============================================================

COMMENT ON TABLE tenant_assets IS
    'Per-tenant brand assets (logos, icon, color/font JSON). One row per asset_type per tenant.';

COMMENT ON COLUMN tenant_assets.asset_type IS
    'logo_light, logo_dark, icon = file uploads; brand_colors_json, brand_fonts_json = JSON config strings stored as file_url.';

COMMENT ON COLUMN tenant_assets.file_url IS
    'Supabase Storage path (e.g. "tenant_001/logo_light.png") for binary assets, '
    'or inline JSON string for brand_colors_json / brand_fonts_json.';
