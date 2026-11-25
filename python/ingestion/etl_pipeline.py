"""End-to-end idempotent Python ETL pipeline: raw -> clean/validate/quarantine -> warehouse."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from data_quality.quality_checks import (
    clean_and_validate_inventory,
    clean_and_validate_order_items,
    clean_and_validate_orders,
    clean_and_validate_stores,
    evaluate_quality_gates_and_report,
    load_validation_rules,
)
from data_quality.quarantine import QuarantineManager
from python.cleaning.normalizer import (
    deduplicate_by_key,
    normalize_cities,
    standardize_timestamps_to_utc,
    to_ist_series,
)
from python.config import PROJECT_ROOT, get_logger, get_simulation_config
from python.db import BackendType, get_engine, initialize_warehouse

logger = get_logger(__name__)


def build_dim_date_time(start_date: str, n_days: int) -> pd.DataFrame:
    """Build hourly IST dim_date_time dimension table."""
    start_ist = pd.Timestamp(start_date, tz="Asia/Kolkata")
    hours = pd.date_range(start=start_ist, periods=n_days * 24, freq="h")

    def _bucket(h: int) -> str:
        if 0 <= h < 6:
            return "LATE_NIGHT"
        if 6 <= h < 11:
            return "MORNING_RUSH"
        if 11 <= h < 16:
            return "LUNCH_AFTERNOON"
        if 16 <= h < 19:
            return "EARLY_EVENING"
        if 19 <= h < 22:
            return "PEAK_EVENING_7_10PM"
        return "NIGHT"

    df = pd.DataFrame({
        "date_time_sk": [int(ts.strftime("%Y%m%d%H")) for ts in hours],
        "full_date": [ts.date().isoformat() for ts in hours],
        "year": hours.year,
        "quarter": hours.quarter,
        "month": hours.month,
        "month_name": hours.strftime("%B"),
        "year_month": hours.strftime("%Y-%m"),
        "week_of_year": hours.isocalendar().week.astype(int).to_numpy(),
        "day_of_week": hours.dayofweek,
        "day_name": hours.strftime("%A"),
        "is_weekend": (hours.dayofweek >= 5),
        "hour_ist": hours.hour,
        "time_bucket": [_bucket(int(h)) for h in hours.hour],
        "is_peak_evening": ((hours.hour >= 19) & (hours.hour <= 21)),
    })
    return df


def _resolve_scd2_sk(
    df_fact: pd.DataFrame,
    bk_col: str,
    ts_col: str,
    dim_df: pd.DataFrame,
    sk_col: str,
) -> pd.Series:
    """Resolve point-in-time SCD Type 2 surrogate key for each fact row."""
    # Split unchanged vs versioned keys for fast vectorized lookup
    counts = dim_df[bk_col].value_counts()
    multi_keys = set(counts[counts > 1].index)

    simple_map = (
        dim_df[~dim_df[bk_col].isin(multi_keys)]
        .set_index(bk_col)[sk_col]
        .to_dict()
    )
    result = df_fact[bk_col].map(simple_map)

    if multi_keys:
        multi_mask = df_fact[bk_col].isin(multi_keys)
        if multi_mask.any():
            sub_fact = df_fact.loc[multi_mask, [bk_col, ts_col]].copy()
            sub_dim = dim_df[dim_df[bk_col].isin(multi_keys)].copy()
            sub_dim["eff_from"] = pd.to_datetime(sub_dim["effective_from"], utc=True)
            sub_dim["eff_to"] = pd.to_datetime(sub_dim["effective_to"], utc=True).fillna(
                pd.Timestamp("2099-12-31T23:59:59Z")
            )
            merged = sub_fact.reset_index().merge(sub_dim[[bk_col, sk_col, "eff_from", "eff_to"]], on=bk_col, how="left")
            matched = merged[(merged[ts_col] >= merged["eff_from"]) & (merged[ts_col] <= merged["eff_to"])]
            matched = matched.drop_duplicates(subset=["index"], keep="last")
            result.loc[matched["index"].values] = matched[sk_col].values

    return result.astype("Int64")


def _bulk_insert_df(
    engine: Engine,
    backend: BackendType,
    table_name: str,
    df: pd.DataFrame,
    schema: str | None = "dw",
    chunksize: int = 20000,
) -> None:
    """Fast chunked insert compatible with both PostgreSQL (schema-qualified) and SQLite."""
    target_schema = schema if backend == "postgres" else None
    df.to_sql(
        name=table_name,
        con=engine,
        schema=target_schema,
        if_exists="append",
        index=False,
        method="multi" if backend == "postgres" else None,
        chunksize=chunksize,
    )


def run_etl_pipeline(strict_gate: bool = True) -> dict[str, Any]:
    """Execute full ETL pipeline: Extract -> Clean/Quarantine -> Quality Gate -> Load Warehouse."""
    raw_dir = PROJECT_ROOT / "data" / "raw"
    proc_dir = PROJECT_ROOT / "data" / "processed"
    proc_dir.mkdir(parents=True, exist_ok=True)

    batch_id = f"BATCH-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    started_at = datetime.now(timezone.utc).isoformat()
    qm = QuarantineManager(batch_id=batch_id)
    rules = load_validation_rules()

    logger.info("Starting ETL batch %s...", batch_id)

    # 1. EXTRACT RAW CSVs
    raw_stores = pd.read_csv(raw_dir / "dark_stores.csv")
    stores_scd = pd.read_csv(raw_dir / "dark_stores_scd_history.csv")
    raw_skus = pd.read_csv(raw_dir / "skus.csv")
    skus_scd = pd.read_csv(raw_dir / "skus_scd_history.csv")
    raw_riders = pd.read_csv(raw_dir / "riders.csv")
    raw_customers = pd.read_csv(raw_dir / "customers.csv")
    raw_weather = pd.read_csv(raw_dir / "weather_data.csv")
    raw_orders = pd.read_csv(raw_dir / "orders.csv")
    raw_items = pd.read_csv(raw_dir / "order_items.csv")
    raw_inv = pd.read_csv(raw_dir / "inventory_snapshots.csv")
    raw_rider_logs = pd.read_csv(raw_dir / "rider_logs.csv")
    raw_ab_assign = pd.read_csv(raw_dir / "ab_experiment_assignments.csv")
    raw_ab_events = pd.read_csv(raw_dir / "ab_experiment_events.csv")

    # 2. CLEAN & NORMALIZE DIMENSIONS
    stores_acc = clean_and_validate_stores(raw_stores, qm)
    valid_store_ids = set(stores_acc["store_id"])
    stores_scd_acc = normalize_cities(stores_scd[stores_scd["store_id"].isin(valid_store_ids)].copy(), "city")

    customers_acc = normalize_cities(raw_customers, col="city")
    customers_acc, cust_dups = deduplicate_by_key(customers_acc, "customer_id")
    qm.add_dataframe(cust_dups, "customers", "customer_id", "DUPLICATE_CUSTOMER_ID", severity="WARNING")

    riders_acc, rider_dups = deduplicate_by_key(raw_riders, "rider_id")
    riders_acc = riders_acc.rename(columns={"assigned_store": "assigned_store_id"})
    skus_acc, _ = deduplicate_by_key(raw_skus, "sku_id")

    valid_customer_ids = set(customers_acc["customer_id"])
    valid_rider_ids = set(riders_acc["rider_id"])
    valid_sku_ids = set(skus_acc["sku_id"])

    # 3. CLEAN & VALIDATE FACTS
    orders_acc, order_stats = clean_and_validate_orders(
        raw_orders=raw_orders,
        valid_store_ids=valid_store_ids,
        valid_customer_ids=valid_customer_ids,
        valid_rider_ids=valid_rider_ids,
        qm=qm,
        rules=rules,
    )
    accepted_order_ids = set(orders_acc["order_id"])

    items_acc, item_stats = clean_and_validate_order_items(
        raw_items=raw_items,
        accepted_order_ids=accepted_order_ids,
        valid_sku_ids=valid_sku_ids,
        qm=qm,
    )

    inv_acc, inv_stats = clean_and_validate_inventory(
        raw_inv=raw_inv,
        valid_store_ids=valid_store_ids,
        valid_sku_ids=valid_sku_ids,
        qm=qm,
    )

    # Clean weather, rider logs, A/B events
    weather_acc = standardize_timestamps_to_utc(raw_weather, ["timestamp_utc"])
    ab_events_acc = standardize_timestamps_to_utc(raw_ab_events, ["event_timestamp"])
    ab_events_acc = ab_events_acc[
        ab_events_acc["customer_id"].isin(valid_customer_ids)
        & (ab_events_acc["order_id"].isna() | ab_events_acc["order_id"].isin(accepted_order_ids))
    ].copy()
    rider_logs_acc = standardize_timestamps_to_utc(raw_rider_logs, ["event_timestamp"])
    rider_logs_acc = rider_logs_acc[
        rider_logs_acc["order_id"].isin(accepted_order_ids)
        & rider_logs_acc["rider_id"].isin(valid_rider_ids)
        & rider_logs_acc["store_id"].isin(valid_store_ids)
    ].copy()

    # 4. QUALITY GATE (Aborts publication if critical gate fails)
    quarantine_csv = qm.write_staging_csv()
    dq_report = evaluate_quality_gates_and_report(
        batch_id=batch_id,
        order_stats=order_stats,
        item_stats=item_stats,
        inv_stats=inv_stats,
        orders_acc=orders_acc,
        items_acc=items_acc,
        stores_acc=stores_acc,
        qm=qm,
        strict=strict_gate,
    )

    # Persist cleaned processed CSVs for downstream fast Python/PowerBI workflows
    stores_acc.to_csv(proc_dir / "dim_dark_stores_clean.csv", index=False)
    stores_scd_acc.to_csv(proc_dir / "dim_dark_stores_scd.csv", index=False)
    skus_scd.to_csv(proc_dir / "dim_skus_scd.csv", index=False)
    customers_acc.to_csv(proc_dir / "dim_customers_clean.csv", index=False)
    riders_acc.to_csv(proc_dir / "dim_riders_clean.csv", index=False)
    orders_acc.to_csv(proc_dir / "fact_orders_clean.csv", index=False)
    items_acc.to_csv(proc_dir / "fact_order_items_clean.csv", index=False)
    inv_acc.to_csv(proc_dir / "fact_inventory_snapshots_clean.csv", index=False)
    weather_acc.to_csv(proc_dir / "fact_weather_clean.csv", index=False)
    raw_ab_assign.to_csv(proc_dir / "ab_experiment_assignments_clean.csv", index=False)
    ab_events_acc.to_csv(proc_dir / "ab_experiment_events_clean.csv", index=False)

    # 5. PUBLISH TO RELATIONAL WAREHOUSE (PostgreSQL or SQLite Mirror)
    sim_cfg = get_simulation_config()
    dim_dt_df = build_dim_date_time(sim_cfg["date_range"]["start_date"], int(sim_cfg["date_range"]["days"]))

    engine, backend = get_engine(allow_sqlite_fallback=True)
    initialize_warehouse(engine, backend)

    prefix = "dw." if backend == "postgres" else ""
    audit_prefix = "audit." if backend == "postgres" else ""

    with engine.begin() as conn:
        # Idempotent clean reload in dependency order
        for tbl in [
            f"{prefix}fact_rider_logs",
            f"{prefix}fact_ab_experiment_events",
            f"{prefix}fact_inventory_snapshots",
            f"{prefix}fact_order_items",
            f"{prefix}fact_orders",
            f"{prefix}fact_weather_observations",
            f"{prefix}ab_experiment_assignments",
            f"{prefix}dim_date_time",
            f"{prefix}dim_skus",
            f"{prefix}dim_riders",
            f"{prefix}dim_customers",
            f"{prefix}dim_dark_stores",
        ]:
            conn.execute(text(f"DELETE FROM {tbl}"))

    # Load Dimensions
    stores_load = stores_scd_acc[[
        "store_id", "store_name", "city", "state", "pincode", "zone",
        "rent_tier", "monthly_rent", "operating_capacity", "staffing_level",
        "effective_from", "effective_to", "is_current",
    ]].copy()
    if backend == "sqlite":
        stores_load["is_current"] = stores_load["is_current"].astype(int)
    _bulk_insert_df(engine, backend, "dim_dark_stores", stores_load, schema="dw")

    skus_load = skus_scd[[
        "sku_id", "sku_name", "category", "subcategory", "unit_cost", "selling_price",
        "gross_margin", "gross_margin_pct", "supplier", "reorder_threshold",
        "effective_from", "effective_to", "is_current",
    ]].copy()
    if backend == "sqlite":
        skus_load["is_current"] = skus_load["is_current"].astype(int)
    _bulk_insert_df(engine, backend, "dim_skus", skus_load, schema="dw")

    _bulk_insert_df(engine, backend, "dim_customers", customers_acc, schema="dw")
    _bulk_insert_df(engine, backend, "dim_riders", riders_acc, schema="dw")

    dt_load = dim_dt_df.copy()
    if backend == "sqlite":
        dt_load["is_weekend"] = dt_load["is_weekend"].astype(int)
        dt_load["is_peak_evening"] = dt_load["is_peak_evening"].astype(int)
    _bulk_insert_df(engine, backend, "dim_date_time", dt_load, schema="dw")

    _bulk_insert_df(engine, backend, "ab_experiment_assignments", raw_ab_assign, schema="dw")

    # Read generated surrogate keys back from warehouse
    dim_stores_db = pd.read_sql(f"SELECT store_sk, store_id, effective_from, effective_to, is_current FROM {prefix}dim_dark_stores", engine)
    dim_skus_db = pd.read_sql(f"SELECT sku_sk, sku_id, effective_from, effective_to, is_current FROM {prefix}dim_skus", engine)
    dim_cust_db = pd.read_sql(f"SELECT customer_sk, customer_id FROM {prefix}dim_customers", engine)
    dim_riders_db = pd.read_sql(f"SELECT rider_sk, rider_id FROM {prefix}dim_riders", engine)

    cust_sk_map = dict(zip(dim_cust_db["customer_id"], dim_cust_db["customer_sk"]))
    rider_sk_map = dict(zip(dim_riders_db["rider_id"], dim_riders_db["rider_sk"]))

    # Prepare fact_orders with SCD2 store_sk and IST date_time_sk
    placed_ist = to_ist_series(orders_acc["placed_at"])
    orders_fact = orders_acc.copy()
    orders_fact["customer_sk"] = orders_fact["customer_id"].map(cust_sk_map).astype("int64")
    orders_fact["store_sk"] = _resolve_scd2_sk(orders_fact, "store_id", "placed_at", dim_stores_db, "store_sk").astype("int64")
    orders_fact["rider_sk"] = orders_fact["rider_id"].map(rider_sk_map).astype("Int64")
    orders_fact["date_time_sk"] = placed_ist.dt.strftime("%Y%m%d%H").astype("int64")

    for ts_col in ["placed_at", "packed_at", "dispatched_at", "delivered_at", "cancelled_at"]:
        orders_fact[ts_col] = orders_fact[ts_col].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    order_cols = [
        "order_id", "customer_sk", "store_sk", "rider_sk", "date_time_sk",
        "placed_at", "packed_at", "dispatched_at", "delivered_at", "cancelled_at",
        "order_status", "payment_mode", "weather_tag",
        "cart_value", "discounts", "delivery_fee", "handling_fee", "surge_fee",
        "gross_margin", "rider_payout", "packaging_cost", "refund_cost", "net_contribution_margin",
        "picking_seconds", "assignment_seconds", "transit_seconds", "total_delivery_seconds",
        "is_sla_breach",
    ]
    orders_load = orders_fact[order_cols].copy()
    if backend == "sqlite":
        orders_load["is_sla_breach"] = orders_load["is_sla_breach"].astype(int)
    _bulk_insert_df(engine, backend, "fact_orders", orders_load, schema="dw")

    # Resolve order_sk for child tables
    fact_orders_db = pd.read_sql(f"SELECT order_sk, order_id, placed_at FROM {prefix}fact_orders", engine)
    fact_orders_db["placed_at_dt"] = pd.to_datetime(fact_orders_db["placed_at"], utc=True)
    order_sk_map = dict(zip(fact_orders_db["order_id"], fact_orders_db["order_sk"]))
    order_ts_map = dict(zip(fact_orders_db["order_id"], fact_orders_db["placed_at_dt"]))

    # Load fact_order_items (with point-in-time SCD2 sku_sk & preserved historical unit_price/cost)
    items_fact = items_acc.copy()
    items_fact["order_sk"] = items_fact["order_id"].map(order_sk_map).astype("int64")
    items_fact["placed_at_dt"] = items_fact["order_id"].map(order_ts_map)
    items_fact["sku_sk"] = _resolve_scd2_sk(items_fact, "sku_id", "placed_at_dt", dim_skus_db, "sku_sk").astype("int64")
    items_fact = items_fact.rename(columns={
        "unit_price": "historical_unit_price",
        "unit_cost": "historical_unit_cost",
    })
    items_load = items_fact[[
        "order_item_id", "order_sk", "order_id", "sku_sk",
        "quantity", "historical_unit_price", "historical_unit_cost",
        "line_total", "line_gross_margin",
    ]]
    _bulk_insert_df(engine, backend, "fact_order_items", items_load, schema="dw")

    # Load fact_inventory_snapshots (current/point-in-time store_sk & sku_sk)
    inv_fact = inv_acc.copy()
    inv_fact["store_sk"] = _resolve_scd2_sk(inv_fact, "store_id", "snapshot_timestamp", dim_stores_db, "store_sk").astype("int64")
    inv_fact["sku_sk"] = _resolve_scd2_sk(inv_fact, "sku_id", "snapshot_timestamp", dim_skus_db, "sku_sk").astype("int64")
    inv_fact["snapshot_timestamp"] = inv_fact["snapshot_timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    inv_load = inv_fact[[
        "snapshot_id", "store_sk", "sku_sk", "snapshot_timestamp",
        "stock_on_hand", "reorder_threshold", "is_stockout",
    ]].copy()
    if backend == "sqlite":
        inv_load["is_stockout"] = inv_load["is_stockout"].astype(int)
    _bulk_insert_df(engine, backend, "fact_inventory_snapshots", inv_load, schema="dw", chunksize=40000)

    # Load fact_ab_experiment_events
    ab_fact = ab_events_acc.copy()
    ab_fact["customer_sk"] = ab_fact["customer_id"].map(cust_sk_map).astype("int64")
    ab_fact["order_sk"] = ab_fact["order_id"].map(order_sk_map).astype("Int64")
    ab_fact["event_timestamp"] = ab_fact["event_timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ab_load = ab_fact[[
        "event_id", "customer_sk", "order_sk", "experiment_name",
        "variant", "event_type", "cart_value", "net_contribution", "event_timestamp",
    ]]
    _bulk_insert_df(engine, backend, "fact_ab_experiment_events", ab_load, schema="dw")

    # Load weather observations & rider logs
    w_load = weather_acc[["weather_id", "city", "timestamp_utc", "weather_tag", "rainfall_mm_hr", "temperature_c"]].copy()
    w_load["timestamp_utc"] = w_load["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    _bulk_insert_df(engine, backend, "fact_weather_observations", w_load, schema="dw")

    curr_store_map = dict(zip(dim_stores_db[dim_stores_db["is_current"] == True]["store_id"], dim_stores_db[dim_stores_db["is_current"] == True]["store_sk"]))
    rl_fact = rider_logs_acc.copy()
    rl_fact["rider_sk"] = rl_fact["rider_id"].map(rider_sk_map).astype("int64")
    rl_fact["store_sk"] = rl_fact["store_id"].map(curr_store_map).astype("int64")
    rl_fact["order_sk"] = rl_fact["order_id"].map(order_sk_map).astype("Int64")
    rl_fact["event_timestamp"] = rl_fact["event_timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    _bulk_insert_df(engine, backend, "fact_rider_logs", rl_fact[["log_id", "rider_sk", "store_sk", "order_sk", "event_type", "event_timestamp"]], schema="dw", chunksize=40000)

    # Load Quarantine & ETL Batch Audit
    q_df = qm.to_dataframe()
    if not q_df.empty:
        _bulk_insert_df(engine, backend, "data_quarantine", q_df, schema="audit")

    audit_row = pd.DataFrame([{
        "batch_id": batch_id,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": "SUCCEEDED",
        "raw_orders_count": order_stats["raw_count"],
        "accepted_orders": order_stats["accepted_count"],
        "rejected_orders": order_stats["rejected_validation"] + order_stats["duplicates_dropped"],
        "quarantined_records": len(q_df),
        "quality_gate_passed": 1 if backend == "sqlite" else True,
        "report_path": str(PROJECT_ROOT / "reports" / "data_quality_report.json"),
    }])
    _bulk_insert_df(engine, backend, "etl_batch_runs", audit_row, schema="audit")

    logger.info(
        "ETL batch %s published successfully to %s warehouse! Accepted orders=%d, quarantined=%d",
        batch_id, backend, len(orders_load), len(q_df),
    )
    return {
        "batch_id": batch_id,
        "backend": backend,
        "quarantine_csv": quarantine_csv,
        "data_quality": dq_report,
    }


if __name__ == "__main__":
    res = run_etl_pipeline(strict_gate=True)
    print(f"Batch: {res['batch_id']} | Backend: {res['backend']} | Accepted Orders: {res['data_quality']['metrics']['orders']['accepted_count']:,}")
