-- ============================================================================
-- QuickCommerceIQ — Raw Staging, Data Quality Audit & Anomaly Quarantine Tables
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS audit;

-- ----------------------------------------------------------------------------
-- RAW STAGING TABLES (Unvalidated landing tables prior to Python ETL & gates)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.raw_dark_stores (
    store_id            TEXT,
    store_name          TEXT,
    city                TEXT,
    state               TEXT,
    pincode             TEXT,
    zone                TEXT,
    rent_tier           TEXT,
    monthly_rent        TEXT,
    operating_capacity  TEXT,
    staffing_level      TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stg.raw_orders (
    order_id            TEXT,
    customer_id         TEXT,
    store_id            TEXT,
    rider_id            TEXT,
    placed_at           TEXT,
    packed_at           TEXT,
    dispatched_at       TEXT,
    delivered_at        TEXT,
    cancelled_at        TEXT,
    order_status        TEXT,
    payment_mode        TEXT,
    cart_value          TEXT,
    discounts           TEXT,
    delivery_fee        TEXT,
    handling_fee        TEXT,
    surge_fee           TEXT,
    gross_margin        TEXT,
    rider_payout        TEXT,
    packaging_cost      TEXT,
    refund_cost         TEXT,
    weather_tag         TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stg.raw_order_items (
    order_item_id       TEXT,
    order_id            TEXT,
    sku_id              TEXT,
    quantity            TEXT,
    unit_price          TEXT,
    unit_cost           TEXT,
    line_total          TEXT,
    line_gross_margin   TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stg.raw_inventory_snapshots (
    snapshot_id         TEXT,
    store_id            TEXT,
    sku_id              TEXT,
    snapshot_timestamp  TEXT,
    stock_on_hand       TEXT,
    reorder_threshold   TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- AUDIT & ANOMALY QUARANTINE TABLES
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit.etl_batch_runs (
    batch_id            VARCHAR(64) PRIMARY KEY,
    started_at          TIMESTAMPTZ NOT NULL,
    completed_at        TIMESTAMPTZ,
    status              VARCHAR(20) NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED_GATE', 'ERROR')),
    raw_orders_count    INTEGER NOT NULL DEFAULT 0,
    accepted_orders     INTEGER NOT NULL DEFAULT 0,
    rejected_orders     INTEGER NOT NULL DEFAULT 0,
    quarantined_records INTEGER NOT NULL DEFAULT 0,
    quality_gate_passed BOOLEAN NOT NULL DEFAULT FALSE,
    report_path         TEXT
);

CREATE TABLE IF NOT EXISTS audit.data_quarantine (
    quarantine_sk       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id            VARCHAR(64) NOT NULL,
    entity_type         VARCHAR(40) NOT NULL,
    business_key        VARCHAR(80),
    rejection_reason    VARCHAR(120) NOT NULL,
    severity            VARCHAR(20) NOT NULL DEFAULT 'ERROR',
    raw_payload         JSONB NOT NULL,
    quarantined_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
