-- ============================================================================
-- QuickCommerceIQ — PostgreSQL Star Schema DDL (Dimensions & Fact Tables)
-- Target Engine: PostgreSQL 15+
-- Timezone Standard: UTC storage (TIMESTAMPTZ), Asia/Kolkata reporting
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS dw;
SET search_path TO dw, public;

-- ----------------------------------------------------------------------------
-- 1. DIMENSION: dim_dark_stores (SCD Type 2 for rent_tier, monthly_rent, staffing)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_dark_stores (
    store_sk            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id            VARCHAR(20) NOT NULL,
    store_name          VARCHAR(120) NOT NULL,
    city                VARCHAR(50) NOT NULL,
    state               VARCHAR(50) NOT NULL,
    pincode             CHAR(6) NOT NULL CHECK (pincode ~ '^[0-9]{6}$'),
    zone                VARCHAR(60) NOT NULL,
    rent_tier           VARCHAR(20) NOT NULL CHECK (rent_tier IN ('PREMIUM', 'HIGH_STREET', 'STANDARD')),
    monthly_rent        NUMERIC(12, 2) NOT NULL CHECK (monthly_rent >= 0),
    operating_capacity  INTEGER NOT NULL CHECK (operating_capacity > 0),
    staffing_level      INTEGER NOT NULL CHECK (staffing_level > 0),
    effective_from      TIMESTAMPTZ NOT NULL,
    effective_to        TIMESTAMPTZ,
    is_current          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_dim_dark_stores_bk_eff UNIQUE (store_id, effective_from)
);

-- ----------------------------------------------------------------------------
-- 2. DIMENSION: dim_customers
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_customers (
    customer_sk         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id         VARCHAR(20) NOT NULL UNIQUE,
    acquisition_channel VARCHAR(30) NOT NULL,
    customer_segment    VARCHAR(30) NOT NULL,
    city                VARCHAR(50) NOT NULL,
    home_store_id       VARCHAR(20) NOT NULL,
    registration_date   DATE NOT NULL,
    first_order_date    DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- 3. DIMENSION: dim_riders
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_riders (
    rider_sk            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rider_id            VARCHAR(20) NOT NULL UNIQUE,
    vehicle_type        VARCHAR(20) NOT NULL CHECK (vehicle_type IN ('EV_SCOOTER', 'PETROL_BIKE', 'BICYCLE')),
    employment_type     VARCHAR(20) NOT NULL CHECK (employment_type IN ('FULL_TIME', 'GIG_PART_TIME')),
    payout_tier         VARCHAR(20) NOT NULL CHECK (payout_tier IN ('BASE', 'TIER_1', 'TIER_2')),
    assigned_store_id   VARCHAR(20) NOT NULL,
    availability_status VARCHAR(20) NOT NULL CHECK (availability_status IN ('ACTIVE', 'ON_LEAVE', 'OFFLINE')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- 4. DIMENSION: dim_skus (SCD Type 2 for unit_cost and selling_price history)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_skus (
    sku_sk              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku_id              VARCHAR(20) NOT NULL,
    sku_name            VARCHAR(160) NOT NULL,
    category            VARCHAR(60) NOT NULL,
    subcategory         VARCHAR(60) NOT NULL,
    unit_cost           NUMERIC(12, 2) NOT NULL CHECK (unit_cost > 0),
    selling_price       NUMERIC(12, 2) NOT NULL CHECK (selling_price > 0),
    gross_margin        NUMERIC(12, 2) NOT NULL,
    gross_margin_pct    NUMERIC(6, 2) NOT NULL,
    supplier            VARCHAR(100) NOT NULL,
    reorder_threshold   INTEGER NOT NULL CHECK (reorder_threshold >= 0),
    effective_from      TIMESTAMPTZ NOT NULL,
    effective_to        TIMESTAMPTZ,
    is_current          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_dim_skus_bk_eff UNIQUE (sku_id, effective_from)
);

-- ----------------------------------------------------------------------------
-- 5. DIMENSION: dim_date_time (Hourly IST Grain: YYYYMMDDHH)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_date_time (
    date_time_sk        BIGINT PRIMARY KEY,
    full_date           DATE NOT NULL,
    year                SMALLINT NOT NULL,
    quarter             SMALLINT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month               SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name          VARCHAR(15) NOT NULL,
    year_month          CHAR(7) NOT NULL,
    week_of_year        SMALLINT NOT NULL,
    day_of_week         SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    day_name            VARCHAR(15) NOT NULL,
    is_weekend          BOOLEAN NOT NULL,
    hour_ist            SMALLINT NOT NULL CHECK (hour_ist BETWEEN 0 AND 23),
    time_bucket         VARCHAR(25) NOT NULL,
    is_peak_evening     BOOLEAN NOT NULL
);

-- ----------------------------------------------------------------------------
-- 6. CUSTOMER EXPERIMENT ASSIGNMENTS (Persistent Randomization Registry)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.ab_experiment_assignments (
    assignment_sk       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id         VARCHAR(20) NOT NULL REFERENCES dw.dim_customers(customer_id),
    experiment_name     VARCHAR(80) NOT NULL,
    variant             VARCHAR(20) NOT NULL CHECK (variant IN ('CONTROL', 'TREATMENT')),
    threshold_inr       NUMERIC(12, 2) NOT NULL,
    assigned_at         TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_ab_assign_cust_exp UNIQUE (customer_id, experiment_name)
);

-- ----------------------------------------------------------------------------
-- 7. FACT: fact_orders (Grain: 1 row per order)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.fact_orders (
    order_sk                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id                VARCHAR(25) NOT NULL UNIQUE,
    customer_sk             BIGINT NOT NULL REFERENCES dw.dim_customers(customer_sk),
    store_sk                BIGINT NOT NULL REFERENCES dw.dim_dark_stores(store_sk),
    rider_sk                BIGINT REFERENCES dw.dim_riders(rider_sk),
    date_time_sk            BIGINT NOT NULL REFERENCES dw.dim_date_time(date_time_sk),
    placed_at               TIMESTAMPTZ NOT NULL,
    packed_at               TIMESTAMPTZ,
    dispatched_at           TIMESTAMPTZ,
    delivered_at            TIMESTAMPTZ,
    cancelled_at            TIMESTAMPTZ,
    order_status            VARCHAR(20) NOT NULL CHECK (order_status IN ('DELIVERED', 'CANCELLED')),
    payment_mode            VARCHAR(15) NOT NULL CHECK (payment_mode IN ('UPI', 'CARD', 'COD')),
    weather_tag             VARCHAR(20) NOT NULL CHECK (weather_tag IN ('NORMAL', 'MONSOON', 'HEAVY_RAIN')),
    cart_value              NUMERIC(12, 2) NOT NULL CHECK (cart_value >= 0),
    discounts               NUMERIC(12, 2) NOT NULL CHECK (discounts >= 0),
    delivery_fee            NUMERIC(12, 2) NOT NULL CHECK (delivery_fee >= 0),
    handling_fee            NUMERIC(12, 2) NOT NULL CHECK (handling_fee >= 0),
    surge_fee               NUMERIC(12, 2) NOT NULL CHECK (surge_fee >= 0),
    gross_margin            NUMERIC(12, 2) NOT NULL,
    rider_payout            NUMERIC(12, 2) NOT NULL CHECK (rider_payout >= 0),
    packaging_cost          NUMERIC(12, 2) NOT NULL CHECK (packaging_cost >= 0),
    refund_cost             NUMERIC(12, 2) NOT NULL CHECK (refund_cost >= 0),
    net_contribution_margin NUMERIC(12, 2) NOT NULL,
    picking_seconds         INTEGER,
    assignment_seconds      INTEGER,
    transit_seconds         INTEGER,
    total_delivery_seconds  INTEGER,
    is_sla_breach           BOOLEAN NOT NULL DEFAULT FALSE,
    loaded_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_delivered_timestamps CHECK (
        order_status <> 'DELIVERED'
        OR (packed_at IS NOT NULL AND dispatched_at IS NOT NULL AND delivered_at IS NOT NULL AND rider_sk IS NOT NULL)
    )
);

-- ----------------------------------------------------------------------------
-- 8. FACT: fact_order_items (Grain: 1 row per order-SKU combination)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.fact_order_items (
    order_item_sk           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_item_id           VARCHAR(30) NOT NULL UNIQUE,
    order_sk                BIGINT NOT NULL REFERENCES dw.fact_orders(order_sk) ON DELETE CASCADE,
    order_id                VARCHAR(25) NOT NULL,
    sku_sk                  BIGINT NOT NULL REFERENCES dw.dim_skus(sku_sk),
    quantity                INTEGER NOT NULL CHECK (quantity > 0),
    historical_unit_price   NUMERIC(12, 2) NOT NULL CHECK (historical_unit_price > 0),
    historical_unit_cost    NUMERIC(12, 2) NOT NULL CHECK (historical_unit_cost > 0),
    line_total              NUMERIC(12, 2) NOT NULL CHECK (line_total >= 0),
    line_gross_margin       NUMERIC(12, 2) NOT NULL,
    CONSTRAINT uq_fact_order_items_order_sku UNIQUE (order_sk, sku_sk)
);

-- ----------------------------------------------------------------------------
-- 9. FACT: fact_inventory_snapshots (Grain: 1 row per store-SKU-snapshot timestamp)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.fact_inventory_snapshots (
    snapshot_sk         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id         VARCHAR(30) NOT NULL UNIQUE,
    store_sk            BIGINT NOT NULL REFERENCES dw.dim_dark_stores(store_sk),
    sku_sk              BIGINT NOT NULL REFERENCES dw.dim_skus(sku_sk),
    snapshot_timestamp  TIMESTAMPTZ NOT NULL,
    stock_on_hand       INTEGER NOT NULL CHECK (stock_on_hand >= 0),
    reorder_threshold   INTEGER NOT NULL CHECK (reorder_threshold >= 0),
    is_stockout         BOOLEAN NOT NULL,
    CONSTRAINT uq_fact_inv_store_sku_ts UNIQUE (store_sk, sku_sk, snapshot_timestamp)
);

-- ----------------------------------------------------------------------------
-- 10. FACT: fact_ab_experiment_events (Grain: 1 row per customer experiment event)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.fact_ab_experiment_events (
    event_sk            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id            VARCHAR(30) NOT NULL UNIQUE,
    customer_sk         BIGINT NOT NULL REFERENCES dw.dim_customers(customer_sk),
    order_sk            BIGINT REFERENCES dw.fact_orders(order_sk),
    experiment_name     VARCHAR(80) NOT NULL,
    variant             VARCHAR(20) NOT NULL CHECK (variant IN ('CONTROL', 'TREATMENT')),
    event_type          VARCHAR(30) NOT NULL,
    cart_value          NUMERIC(12, 2) NOT NULL CHECK (cart_value >= 0),
    net_contribution    NUMERIC(12, 2) NOT NULL,
    event_timestamp     TIMESTAMPTZ NOT NULL
);

-- ----------------------------------------------------------------------------
-- 11. SUPPORTING FACTS: Weather Observations & Rider Activity Logs
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.fact_weather_observations (
    weather_sk          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    weather_id          VARCHAR(25) NOT NULL UNIQUE,
    city                VARCHAR(50) NOT NULL,
    timestamp_utc       TIMESTAMPTZ NOT NULL,
    weather_tag         VARCHAR(20) NOT NULL CHECK (weather_tag IN ('NORMAL', 'MONSOON', 'HEAVY_RAIN')),
    rainfall_mm_hr      NUMERIC(6, 2) NOT NULL CHECK (rainfall_mm_hr >= 0),
    temperature_c       NUMERIC(5, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.fact_rider_logs (
    rider_log_sk        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    log_id              VARCHAR(30) NOT NULL UNIQUE,
    rider_sk            BIGINT NOT NULL REFERENCES dw.dim_riders(rider_sk),
    store_sk            BIGINT NOT NULL REFERENCES dw.dim_dark_stores(store_sk),
    order_sk            BIGINT REFERENCES dw.fact_orders(order_sk),
    event_type          VARCHAR(25) NOT NULL,
    event_timestamp     TIMESTAMPTZ NOT NULL
);
