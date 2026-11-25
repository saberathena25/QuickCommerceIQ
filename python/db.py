"""Database connection, DDL initialization, and dual PostgreSQL/SQLite warehouse helper."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from python.config import PROJECT_ROOT, get_logger

logger = get_logger(__name__)

BackendType = Literal["postgres", "sqlite"]


def get_database_config() -> tuple[BackendType, str]:
    """Resolve active database backend and SQLAlchemy URL."""
    backend = os.getenv("DB_BACKEND", "postgres").strip().lower()
    sqlite_rel = os.getenv("SQLITE_DB_PATH", "data/processed/quickcommerce_warehouse.db")
    sqlite_path = (PROJECT_ROOT / sqlite_rel).resolve()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    sqlite_url = f"sqlite:///{sqlite_path.as_posix()}"

    if backend == "sqlite":
        return "sqlite", sqlite_url

    pg_url = os.getenv("DATABASE_URL")
    if not pg_url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "quickcommerce_iq")
        user = os.getenv("POSTGRES_USER", "qc_admin")
        pwd = os.getenv("POSTGRES_PASSWORD", "")
        pg_url = f"postgresql+psycopg://{user}:{pwd}@{host}:{port}/{db}"
    return "postgres", pg_url


def get_engine(allow_sqlite_fallback: bool = True) -> tuple[Engine, BackendType]:
    """Create a verified SQLAlchemy engine, falling back to local SQLite if Postgres is unavailable."""
    backend, url = get_database_config()
    if backend == "postgres":
        try:
            eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Connected to PostgreSQL warehouse.")
            return eng, "postgres"
        except Exception as exc:
            if not allow_sqlite_fallback:
                raise
            logger.warning(
                "PostgreSQL unreachable (%s). Falling back to local SQLite warehouse for execution.",
                exc.__class__.__name__,
            )

    sqlite_rel = os.getenv("SQLITE_DB_PATH", "data/processed/quickcommerce_warehouse.db")
    sqlite_path = (PROJECT_ROOT / sqlite_rel).resolve()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(f"sqlite:///{sqlite_path.as_posix()}")

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.close()

    logger.info("Using local SQLite warehouse mirror at %s", sqlite_path)
    return eng, "sqlite"


SQLITE_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dim_dark_stores (
    store_sk            INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id            TEXT NOT NULL,
    store_name          TEXT NOT NULL,
    city                TEXT NOT NULL,
    state               TEXT NOT NULL,
    pincode             TEXT NOT NULL,
    zone                TEXT NOT NULL,
    rent_tier           TEXT NOT NULL CHECK (rent_tier IN ('PREMIUM', 'HIGH_STREET', 'STANDARD')),
    monthly_rent        REAL NOT NULL CHECK (monthly_rent >= 0),
    operating_capacity  INTEGER NOT NULL CHECK (operating_capacity > 0),
    staffing_level      INTEGER NOT NULL CHECK (staffing_level > 0),
    effective_from      TEXT NOT NULL,
    effective_to        TEXT,
    is_current          INTEGER NOT NULL DEFAULT 1,
    UNIQUE (store_id, effective_from)
);

CREATE TABLE IF NOT EXISTS dim_customers (
    customer_sk         INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id         TEXT NOT NULL UNIQUE,
    acquisition_channel TEXT NOT NULL,
    customer_segment    TEXT NOT NULL,
    city                TEXT NOT NULL,
    home_store_id       TEXT NOT NULL,
    registration_date   TEXT NOT NULL,
    first_order_date    TEXT
);

CREATE TABLE IF NOT EXISTS dim_riders (
    rider_sk            INTEGER PRIMARY KEY AUTOINCREMENT,
    rider_id            TEXT NOT NULL UNIQUE,
    vehicle_type        TEXT NOT NULL,
    employment_type     TEXT NOT NULL,
    payout_tier         TEXT NOT NULL,
    assigned_store_id   TEXT NOT NULL,
    availability_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_skus (
    sku_sk              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id              TEXT NOT NULL,
    sku_name            TEXT NOT NULL,
    category            TEXT NOT NULL,
    subcategory         TEXT NOT NULL,
    unit_cost           REAL NOT NULL CHECK (unit_cost > 0),
    selling_price       REAL NOT NULL CHECK (selling_price > 0),
    gross_margin        REAL NOT NULL,
    gross_margin_pct    REAL NOT NULL,
    supplier            TEXT NOT NULL,
    reorder_threshold   INTEGER NOT NULL CHECK (reorder_threshold >= 0),
    effective_from      TEXT NOT NULL,
    effective_to        TEXT,
    is_current          INTEGER NOT NULL DEFAULT 1,
    UNIQUE (sku_id, effective_from)
);

CREATE TABLE IF NOT EXISTS dim_date_time (
    date_time_sk        INTEGER PRIMARY KEY,
    full_date           TEXT NOT NULL,
    year                INTEGER NOT NULL,
    quarter             INTEGER NOT NULL,
    month               INTEGER NOT NULL,
    month_name          TEXT NOT NULL,
    year_month          TEXT NOT NULL,
    week_of_year        INTEGER NOT NULL,
    day_of_week         INTEGER NOT NULL,
    day_name            TEXT NOT NULL,
    is_weekend          INTEGER NOT NULL,
    hour_ist            INTEGER NOT NULL,
    time_bucket         TEXT NOT NULL,
    is_peak_evening     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ab_experiment_assignments (
    assignment_sk       INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id         TEXT NOT NULL REFERENCES dim_customers(customer_id),
    experiment_name     TEXT NOT NULL,
    variant             TEXT NOT NULL CHECK (variant IN ('CONTROL', 'TREATMENT')),
    threshold_inr       REAL NOT NULL,
    assigned_at         TEXT NOT NULL,
    UNIQUE (customer_id, experiment_name)
);

CREATE TABLE IF NOT EXISTS fact_orders (
    order_sk                INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id                TEXT NOT NULL UNIQUE,
    customer_sk             INTEGER NOT NULL REFERENCES dim_customers(customer_sk),
    store_sk                INTEGER NOT NULL REFERENCES dim_dark_stores(store_sk),
    rider_sk                INTEGER REFERENCES dim_riders(rider_sk),
    date_time_sk            INTEGER NOT NULL REFERENCES dim_date_time(date_time_sk),
    placed_at               TEXT NOT NULL,
    packed_at               TEXT,
    dispatched_at           TEXT,
    delivered_at            TEXT,
    cancelled_at            TEXT,
    order_status            TEXT NOT NULL CHECK (order_status IN ('DELIVERED', 'CANCELLED')),
    payment_mode            TEXT NOT NULL CHECK (payment_mode IN ('UPI', 'CARD', 'COD')),
    weather_tag             TEXT NOT NULL CHECK (weather_tag IN ('NORMAL', 'MONSOON', 'HEAVY_RAIN')),
    cart_value              REAL NOT NULL CHECK (cart_value >= 0),
    discounts               REAL NOT NULL CHECK (discounts >= 0),
    delivery_fee            REAL NOT NULL CHECK (delivery_fee >= 0),
    handling_fee            REAL NOT NULL CHECK (handling_fee >= 0),
    surge_fee               REAL NOT NULL CHECK (surge_fee >= 0),
    gross_margin            REAL NOT NULL,
    rider_payout            REAL NOT NULL CHECK (rider_payout >= 0),
    packaging_cost          REAL NOT NULL CHECK (packaging_cost >= 0),
    refund_cost             REAL NOT NULL CHECK (refund_cost >= 0),
    net_contribution_margin REAL NOT NULL,
    picking_seconds         INTEGER,
    assignment_seconds      INTEGER,
    transit_seconds         INTEGER,
    total_delivery_seconds  INTEGER,
    is_sla_breach           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fact_order_items (
    order_item_sk           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_item_id           TEXT NOT NULL UNIQUE,
    order_sk                INTEGER NOT NULL REFERENCES fact_orders(order_sk) ON DELETE CASCADE,
    order_id                TEXT NOT NULL,
    sku_sk                  INTEGER NOT NULL REFERENCES dim_skus(sku_sk),
    quantity                INTEGER NOT NULL CHECK (quantity > 0),
    historical_unit_price   REAL NOT NULL CHECK (historical_unit_price > 0),
    historical_unit_cost    REAL NOT NULL CHECK (historical_unit_cost > 0),
    line_total              REAL NOT NULL CHECK (line_total >= 0),
    line_gross_margin       REAL NOT NULL,
    UNIQUE (order_sk, sku_sk)
);

CREATE TABLE IF NOT EXISTS fact_inventory_snapshots (
    snapshot_sk         INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id         TEXT NOT NULL UNIQUE,
    store_sk            INTEGER NOT NULL REFERENCES dim_dark_stores(store_sk),
    sku_sk              INTEGER NOT NULL REFERENCES dim_skus(sku_sk),
    snapshot_timestamp  TEXT NOT NULL,
    stock_on_hand       INTEGER NOT NULL CHECK (stock_on_hand >= 0),
    reorder_threshold   INTEGER NOT NULL CHECK (reorder_threshold >= 0),
    is_stockout         INTEGER NOT NULL,
    UNIQUE (store_sk, sku_sk, snapshot_timestamp)
);

CREATE TABLE IF NOT EXISTS fact_ab_experiment_events (
    event_sk            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            TEXT NOT NULL UNIQUE,
    customer_sk         INTEGER NOT NULL REFERENCES dim_customers(customer_sk),
    order_sk            INTEGER REFERENCES fact_orders(order_sk),
    experiment_name     TEXT NOT NULL,
    variant             TEXT NOT NULL CHECK (variant IN ('CONTROL', 'TREATMENT')),
    event_type          TEXT NOT NULL,
    cart_value          REAL NOT NULL CHECK (cart_value >= 0),
    net_contribution    REAL NOT NULL,
    event_timestamp     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_weather_observations (
    weather_sk          INTEGER PRIMARY KEY AUTOINCREMENT,
    weather_id          TEXT NOT NULL UNIQUE,
    city                TEXT NOT NULL,
    timestamp_utc       TEXT NOT NULL,
    weather_tag         TEXT NOT NULL,
    rainfall_mm_hr      REAL NOT NULL,
    temperature_c       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_rider_logs (
    rider_log_sk        INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id              TEXT NOT NULL UNIQUE,
    rider_sk            INTEGER NOT NULL REFERENCES dim_riders(rider_sk),
    store_sk            INTEGER NOT NULL REFERENCES dim_dark_stores(store_sk),
    order_sk            INTEGER REFERENCES fact_orders(order_sk),
    event_type          TEXT NOT NULL,
    event_timestamp     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etl_batch_runs (
    batch_id            TEXT PRIMARY KEY,
    started_at          TEXT NOT NULL,
    completed_at        TEXT,
    status              TEXT NOT NULL,
    raw_orders_count    INTEGER NOT NULL DEFAULT 0,
    accepted_orders     INTEGER NOT NULL DEFAULT 0,
    rejected_orders     INTEGER NOT NULL DEFAULT 0,
    quarantined_records INTEGER NOT NULL DEFAULT 0,
    quality_gate_passed INTEGER NOT NULL DEFAULT 0,
    report_path         TEXT
);

CREATE TABLE IF NOT EXISTS data_quarantine (
    quarantine_sk       INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id            TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    business_key        TEXT,
    rejection_reason    TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'ERROR',
    raw_payload         TEXT NOT NULL,
    quarantined_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sq_orders_store_dt ON fact_orders(store_sk, date_time_sk);
CREATE INDEX IF NOT EXISTS idx_sq_orders_cust_status ON fact_orders(customer_sk, order_status);
CREATE INDEX IF NOT EXISTS idx_sq_order_items_order ON fact_order_items(order_sk);
CREATE INDEX IF NOT EXISTS idx_sq_inv_store_sku_ts ON fact_inventory_snapshots(store_sk, sku_sk, snapshot_timestamp);
CREATE INDEX IF NOT EXISTS idx_sq_ab_events_var ON fact_ab_experiment_events(experiment_name, variant, event_type);
"""


def initialize_warehouse(engine: Engine, backend: BackendType) -> None:
    """Initialize DDL schemas, tables, constraints, and indexes."""
    if backend == "postgres":
        ddl_files = [
            PROJECT_ROOT / "sql" / "ddl" / "01_init_warehouse.sql",
            PROJECT_ROOT / "sql" / "ddl" / "02_staging_and_audit.sql",
            PROJECT_ROOT / "sql" / "ddl" / "03_indexes_and_constraints.sql",
        ]
        raw_conn = engine.raw_connection()
        try:
            with raw_conn.cursor() as cur:
                for sql_path in ddl_files:
                    cur.execute(sql_path.read_text(encoding="utf-8"))
            raw_conn.commit()
        finally:
            raw_conn.close()
        logger.info("Initialized PostgreSQL Star Schema DDL successfully.")
    else:
        raw_conn = engine.raw_connection()
        try:
            raw_conn.executescript(SQLITE_DDL)
            raw_conn.commit()
        finally:
            raw_conn.close()
        logger.info("Initialized SQLite Star Schema mirror DDL successfully.")
