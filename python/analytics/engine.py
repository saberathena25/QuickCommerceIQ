"""Core Business Analytics Engine reading from the relational warehouse and generating BI-ready outputs."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from python.config import PROJECT_ROOT, get_logger, get_settings
from python.db import get_engine

logger = get_logger(__name__)


def _table_prefix(backend: str) -> str:
    return "dw." if backend == "postgres" else ""


def run_unit_economics(engine, backend: str, out_dir) -> dict[str, Any]:
    """Compute Net Contribution Margin across time, store, city, weather, payment mode, and hour."""
    p = _table_prefix(backend)
    orders_sql = f"""
        SELECT
            fo.order_id,
            fo.order_status,
            fo.payment_mode,
            fo.weather_tag,
            fo.cart_value,
            fo.discounts,
            fo.delivery_fee,
            fo.handling_fee,
            fo.surge_fee,
            fo.gross_margin,
            fo.rider_payout,
            fo.packaging_cost,
            fo.refund_cost,
            fo.net_contribution_margin,
            ds.store_id,
            ds.store_name,
            ds.city,
            ds.zone,
            ds.rent_tier,
            ds.monthly_rent,
            dt.full_date,
            dt.year_month,
            dt.hour_ist
        FROM {p}fact_orders fo
        JOIN {p}dim_dark_stores ds ON fo.store_sk = ds.store_sk
        JOIN {p}dim_date_time dt ON fo.date_time_sk = dt.date_time_sk
    """
    df = pd.read_sql(orders_sql, engine)

    # Validate NCM formula explicitly against components
    calc_ncm = (
        df["gross_margin"]
        + df["handling_fee"]
        + df["delivery_fee"]
        + df["surge_fee"]
        - df["discounts"]
        - df["rider_payout"]
        - df["packaging_cost"]
        - df["refund_cost"]
    ).round(2)
    max_diff = float((df["net_contribution_margin"] - calc_ncm).abs().max())
    if max_diff > 0.02:
        raise ValueError(f"NCM validation mismatch detected: max_diff={max_diff}")

    monthly = (
        df.groupby("year_month", as_index=False)
        .agg(
            total_orders=("order_id", "count"),
            delivered_orders=("order_status", lambda s: int((s == "DELIVERED").sum())),
            total_gmv_inr=("cart_value", "sum"),
            total_gross_margin_inr=("gross_margin", "sum"),
            total_ncm_inr=("net_contribution_margin", "sum"),
            avg_ncm_per_order_inr=("net_contribution_margin", "mean"),
            avg_cart_value_inr=("cart_value", "mean"),
            avg_discount_inr=("discounts", "mean"),
            avg_rider_payout_inr=("rider_payout", "mean"),
            avg_refund_inr=("refund_cost", "mean"),
        )
        .sort_values("year_month")
    )
    monthly.to_csv(out_dir / "analytics_ncm_monthly.csv", index=False)

    daily = (
        df.groupby("full_date", as_index=False)
        .agg(
            orders=("order_id", "count"),
            total_gmv_inr=("cart_value", "sum"),
            total_ncm_inr=("net_contribution_margin", "sum"),
            avg_ncm_per_order_inr=("net_contribution_margin", "mean"),
        )
        .sort_values("full_date")
    )
    daily.to_csv(out_dir / "analytics_ncm_daily.csv", index=False)

    # Store-level order NCM vs Fixed Cost (6 months rent + ~15% utilities)
    store_ncm = (
        df.groupby(["store_id", "store_name", "city", "zone"], as_index=False)
        .agg(
            total_orders=("order_id", "count"),
            total_gmv_inr=("cart_value", "sum"),
            order_level_ncm_inr=("net_contribution_margin", "sum"),
            avg_ncm_per_order_inr=("net_contribution_margin", "mean"),
            avg_rider_payout_inr=("rider_payout", "mean"),
            avg_discount_inr=("discounts", "mean"),
            avg_refund_inr=("refund_cost", "mean"),
            total_discounts_inr=("discounts", "sum"),
            current_monthly_rent_inr=("monthly_rent", "max"),
        )
    )
    store_ncm["six_month_fixed_cost_inr"] = np.round(store_ncm["current_monthly_rent_inr"] * 6.0 * 1.15, 2)
    store_ncm["net_store_operating_profit_inr"] = np.round(
        store_ncm["order_level_ncm_inr"] - store_ncm["six_month_fixed_cost_inr"], 2
    )
    store_ncm["discount_pct_of_gmv"] = np.round(100.0 * store_ncm["total_discounts_inr"] / store_ncm["total_gmv_inr"], 2)
    store_ncm = store_ncm.sort_values("avg_ncm_per_order_inr", ascending=True).reset_index(drop=True)
    store_ncm.to_csv(out_dir / "analytics_ncm_by_store.csv", index=False)
    store_ncm.head(10).to_csv(out_dir / "analytics_bottom_10_stores.csv", index=False)

    by_city = df.groupby("city", as_index=False).agg(
        orders=("order_id", "count"),
        total_gmv_inr=("cart_value", "sum"),
        total_ncm_inr=("net_contribution_margin", "sum"),
        avg_ncm_per_order_inr=("net_contribution_margin", "mean"),
    )
    by_city.to_csv(out_dir / "analytics_ncm_by_city.csv", index=False)

    by_hour = df.groupby("hour_ist", as_index=False).agg(
        orders=("order_id", "count"),
        total_ncm_inr=("net_contribution_margin", "sum"),
        avg_ncm_per_order_inr=("net_contribution_margin", "mean"),
    )
    by_hour.to_csv(out_dir / "analytics_ncm_by_hour.csv", index=False)

    by_weather = df.groupby("weather_tag", as_index=False).agg(
        orders=("order_id", "count"),
        total_ncm_inr=("net_contribution_margin", "sum"),
        avg_ncm_per_order_inr=("net_contribution_margin", "mean"),
        avg_rider_payout_inr=("rider_payout", "mean"),
        avg_surge_fee_inr=("surge_fee", "mean"),
    )
    by_weather.to_csv(out_dir / "analytics_ncm_by_weather.csv", index=False)

    by_payment = df.groupby("payment_mode", as_index=False).agg(
        orders=("order_id", "count"),
        total_ncm_inr=("net_contribution_margin", "sum"),
        avg_ncm_per_order_inr=("net_contribution_margin", "mean"),
        avg_packaging_cost_inr=("packaging_cost", "mean"),
    )
    by_payment.to_csv(out_dir / "analytics_ncm_by_payment.csv", index=False)

    waterfall = pd.DataFrame([
        {"component": "Gross Margin", "avg_inr_per_order": round(float(df["gross_margin"].mean()), 2)},
        {"component": "Handling Fee", "avg_inr_per_order": round(float(df["handling_fee"].mean()), 2)},
        {"component": "Delivery Fee", "avg_inr_per_order": round(float(df["delivery_fee"].mean()), 2)},
        {"component": "Surge Fee", "avg_inr_per_order": round(float(df["surge_fee"].mean()), 2)},
        {"component": "Discounts", "avg_inr_per_order": round(float(-df["discounts"].mean()), 2)},
        {"component": "Rider Payout", "avg_inr_per_order": round(float(-df["rider_payout"].mean()), 2)},
        {"component": "Packaging Cost", "avg_inr_per_order": round(float(-df["packaging_cost"].mean()), 2)},
        {"component": "Refund Cost", "avg_inr_per_order": round(float(-df["refund_cost"].mean()), 2)},
        {"component": "Net Contribution Margin", "avg_inr_per_order": round(float(df["net_contribution_margin"].mean()), 2)},
    ])
    waterfall.to_csv(out_dir / "analytics_unit_economics_waterfall.csv", index=False)

    return {
        "total_orders": int(len(df)),
        "delivered_orders": int((df["order_status"] == "DELIVERED").sum()),
        "total_gmv_inr": round(float(df["cart_value"].sum()), 2),
        "total_ncm_inr": round(float(df["net_contribution_margin"].sum()), 2),
        "avg_ncm_per_order_inr": round(float(df["net_contribution_margin"].mean()), 2),
        "may_avg_ncm_inr": round(float(monthly.iloc[0]["avg_ncm_per_order_inr"]), 2),
        "oct_avg_ncm_inr": round(float(monthly.iloc[-1]["avg_ncm_per_order_inr"]), 2),
        "bleeding_stores_count_order_level": int((store_ncm["avg_ncm_per_order_inr"] < 0).sum()),
        "bleeding_stores_count_after_rent": int((store_ncm["net_store_operating_profit_inr"] < 0).sum()),
    }


def run_sla_analysis(engine, backend: str, out_dir) -> dict[str, Any]:
    """Compute SLA decomposition, percentiles, LAG hourly deltas, rolling 30-min congestion, and bottlenecks."""
    p = _table_prefix(backend)
    sql = f"""
        SELECT
            fo.order_id,
            fo.placed_at,
            fo.weather_tag,
            fo.picking_seconds,
            fo.assignment_seconds,
            fo.transit_seconds,
            fo.total_delivery_seconds,
            fo.is_sla_breach,
            fo.rider_payout,
            fo.net_contribution_margin,
            ds.store_id,
            ds.store_name,
            ds.city,
            dt.hour_ist
        FROM {p}fact_orders fo
        JOIN {p}dim_dark_stores ds ON fo.store_sk = ds.store_sk
        JOIN {p}dim_date_time dt ON fo.date_time_sk = dt.date_time_sk
        WHERE fo.order_status = 'DELIVERED'
    """
    df = pd.read_sql(sql, engine)
    df["picking_min"] = df["picking_seconds"] / 60.0
    df["assignment_min"] = df["assignment_seconds"] / 60.0
    df["transit_min"] = df["transit_seconds"] / 60.0
    df["total_min"] = df["total_delivery_seconds"] / 60.0
    df["placed_dt"] = pd.to_datetime(df["placed_at"], utc=True)

    # Store-level SLA + bottleneck classification
    store_sla = (
        df.groupby(["store_id", "store_name", "city"], as_index=False)
        .agg(
            delivered_orders=("order_id", "count"),
            avg_delivery_min=("total_min", "mean"),
            p50_delivery_min=("total_min", "median"),
            p90_delivery_min=("total_min", lambda s: float(np.percentile(s, 90))),
            p95_delivery_min=("total_min", lambda s: float(np.percentile(s, 95))),
            avg_picking_min=("picking_min", "mean"),
            avg_assignment_min=("assignment_min", "mean"),
            avg_transit_min=("transit_min", "mean"),
            sla_breach_pct=("is_sla_breach", lambda s: round(100.0 * float(s.mean()), 2)),
        )
    )
    store_sla["sla_rank"] = store_sla["sla_breach_pct"].rank(method="min", ascending=True).astype(int)

    def _classify_bottleneck(row) -> str:
        excess = {
            "PICKING": row["avg_picking_min"] - 2.5,
            "RIDER_ASSIGNMENT": row["avg_assignment_min"] - 2.0,
            "TRANSIT": row["avg_transit_min"] - 5.5,
        }
        return max(excess, key=excess.get)

    store_sla["primary_bottleneck"] = store_sla.apply(_classify_bottleneck, axis=1)
    for col in ["avg_delivery_min", "p50_delivery_min", "p90_delivery_min", "p95_delivery_min", "avg_picking_min", "avg_assignment_min", "avg_transit_min"]:
        store_sla[col] = store_sla[col].round(2)
    store_sla = store_sla.sort_values("sla_breach_pct", ascending=False)
    store_sla.to_csv(out_dir / "analytics_sla_by_store.csv", index=False)

    # Hourly SLA with LAG delta
    hourly = (
        df.groupby("hour_ist", as_index=False)
        .agg(
            delivered_orders=("order_id", "count"),
            sla_breach_pct=("is_sla_breach", lambda s: round(100.0 * float(s.mean()), 2)),
            avg_delivery_min=("total_min", "mean"),
            avg_picking_min=("picking_min", "mean"),
            avg_assignment_min=("assignment_min", "mean"),
            avg_transit_min=("transit_min", "mean"),
        )
        .sort_values("hour_ist")
    )
    hourly["breach_delta_prev_hr"] = hourly["sla_breach_pct"].diff().round(2)
    hourly["primary_bottleneck"] = hourly.apply(_classify_bottleneck, axis=1)
    for col in ["avg_delivery_min", "avg_picking_min", "avg_assignment_min", "avg_transit_min"]:
        hourly[col] = hourly[col].round(2)
    hourly.to_csv(out_dir / "analytics_sla_by_hour.csv", index=False)

    # City-level SLA
    city_sla = df.groupby("city", as_index=False).agg(
        delivered_orders=("order_id", "count"),
        avg_delivery_min=("total_min", "mean"),
        p90_delivery_min=("total_min", lambda s: float(np.percentile(s, 90))),
        sla_breach_pct=("is_sla_breach", lambda s: round(100.0 * float(s.mean()), 2)),
        avg_picking_min=("picking_min", "mean"),
        avg_assignment_min=("assignment_min", "mean"),
        avg_transit_min=("transit_min", "mean"),
    )
    city_sla.to_csv(out_dir / "analytics_sla_by_city.csv", index=False)

    # Weather SLA comparison
    weather_sla = df.groupby("weather_tag", as_index=False).agg(
        delivered_orders=("order_id", "count"),
        avg_delivery_min=("total_min", "mean"),
        p90_delivery_min=("total_min", lambda s: float(np.percentile(s, 90))),
        sla_breach_pct=("is_sla_breach", lambda s: round(100.0 * float(s.mean()), 2)),
        avg_assignment_min=("assignment_min", "mean"),
        avg_transit_min=("transit_min", "mean"),
        avg_rider_payout_inr=("rider_payout", "mean"),
        avg_ncm_inr=("net_contribution_margin", "mean"),
    )
    weather_sla.to_csv(out_dir / "analytics_sla_by_weather.csv", index=False)

    # Rolling 30-minute operational window (vectorized per store using pandas rolling time window)
    df_roll = df[["store_id", "placed_dt", "total_min", "is_sla_breach"]].sort_values(["store_id", "placed_dt"]).copy()
    roll_frames = []
    for sid, grp in df_roll.groupby("store_id"):
        g = grp.set_index("placed_dt")
        r_count = g["total_min"].rolling("30min").count()
        r_mean = g["total_min"].rolling("30min").mean()
        r_breach = g["is_sla_breach"].rolling("30min").mean() * 100.0
        out_g = pd.DataFrame({
            "store_id": sid,
            "placed_dt": g.index,
            "rolling_30m_orders": r_count.values,
            "rolling_30m_avg_min": np.round(r_mean.values, 2),
            "rolling_30m_breach_pct": np.round(r_breach.values, 2),
        })
        roll_frames.append(out_g)
    roll_df = pd.concat(roll_frames, ignore_index=True)
    roll_summary = (
        roll_df.assign(load_bucket=pd.cut(roll_df["rolling_30m_orders"], bins=[0, 2, 5, 8, 100], labels=["1-2 orders/30m", "3-5 orders/30m", "6-8 orders/30m", "9+ orders/30m"]))
        .groupby("load_bucket", observed=False, as_index=False)
        .agg(
            observations=("store_id", "count"),
            avg_delivery_min=("rolling_30m_avg_min", "mean"),
            avg_breach_pct=("rolling_30m_breach_pct", "mean"),
        )
    )
    roll_summary.to_csv(out_dir / "analytics_rolling_30m_congestion.csv", index=False)

    return {
        "avg_delivery_min": round(float(df["total_min"].mean()), 2),
        "p50_delivery_min": round(float(df["total_min"].median()), 2),
        "p90_delivery_min": round(float(np.percentile(df["total_min"], 90)), 2),
        "p95_delivery_min": round(float(np.percentile(df["total_min"], 95)), 2),
        "overall_sla_breach_pct": round(100.0 * float(df["is_sla_breach"].mean()), 2),
        "avg_picking_min": round(float(df["picking_min"].mean()), 2),
        "avg_assignment_min": round(float(df["assignment_min"].mean()), 2),
        "avg_transit_min": round(float(df["transit_min"].mean()), 2),
        "peak_hour_worst_breach_hour": int(hourly.sort_values("sla_breach_pct", ascending=False).iloc[0]["hour_ist"]),
        "peak_hour_worst_breach_pct": float(hourly["sla_breach_pct"].max()),
        "normal_weather_breach_pct": round(float(weather_sla.loc[weather_sla["weather_tag"] == "NORMAL", "sla_breach_pct"].iloc[0]), 2),
        "heavy_rain_breach_pct": round(float(weather_sla.loc[weather_sla["weather_tag"] == "HEAVY_RAIN", "sla_breach_pct"].iloc[0]), 2),
    }


def run_cohort_retention(engine, backend: str, out_dir) -> dict[str, Any]:
    """Calculate Month 0-6 customer retention segmented by first delivered order SLA."""
    p = _table_prefix(backend)
    sql = f"""
        SELECT
            fo.customer_sk,
            fo.placed_at,
            fo.total_delivery_seconds
        FROM {p}fact_orders fo
        WHERE fo.order_status = 'DELIVERED'
    """
    df = pd.read_sql(sql, engine)
    df["placed_dt"] = pd.to_datetime(df["placed_at"], utc=True)
    df["placed_ist"] = df["placed_dt"].dt.tz_convert("Asia/Kolkata")
    df["order_month"] = df["placed_ist"].dt.to_period("M")

    # First delivered order per customer
    df_sorted = df.sort_values(["customer_sk", "placed_dt"])
    first_ord = df_sorted.drop_duplicates("customer_sk", keep="first").copy()
    first_ord["sla_segment"] = np.where(
        first_ord["total_delivery_seconds"] < 720,
        "FAST (<12m)",
        np.where(first_ord["total_delivery_seconds"] <= 1200, "MEDIUM (12-20m)", "SLOW (>20m)"),
    )
    first_ord = first_ord[["customer_sk", "order_month", "sla_segment"]].rename(columns={"order_month": "cohort_month"})

    cust_months = df[["customer_sk", "order_month"]].drop_duplicates()
    merged = cust_months.merge(first_ord, on="customer_sk", how="inner")
    merged["month_number"] = (merged["order_month"] - merged["cohort_month"]).apply(lambda p_diff: p_diff.n)
    merged = merged[(merged["month_number"] >= 0) & (merged["month_number"] <= 6)]

    cohort_sizes = first_ord.groupby(["sla_segment", "cohort_month"], as_index=False).agg(cohort_size=("customer_sk", "nunique"))
    cohort_act = merged.groupby(["sla_segment", "cohort_month", "month_number"], as_index=False).agg(active_customers=("customer_sk", "nunique"))
    cohort_tbl = cohort_act.merge(cohort_sizes, on=["sla_segment", "cohort_month"], how="left")
    cohort_tbl["retention_pct"] = np.round(100.0 * cohort_tbl["active_customers"] / cohort_tbl["cohort_size"], 2)
    cohort_tbl["cohort_month"] = cohort_tbl["cohort_month"].astype(str)
    cohort_tbl.to_csv(out_dir / "analytics_cohort_retention_matrix.csv", index=False)

    # Aggregated retention curve across cohorts (weighted by eligible cohort size)
    seg_summary = (
        cohort_tbl.groupby(["sla_segment", "month_number"], as_index=False)
        .agg(total_active=("active_customers", "sum"), total_eligible=("cohort_size", "sum"))
    )
    seg_summary["retention_pct"] = np.round(100.0 * seg_summary["total_active"] / seg_summary["total_eligible"], 2)
    seg_summary.to_csv(out_dir / "analytics_cohort_retention_by_sla.csv", index=False)

    m1_fast = float(seg_summary[(seg_summary["sla_segment"] == "FAST (<12m)") & (seg_summary["month_number"] == 1)]["retention_pct"].iloc[0])
    m1_slow = float(seg_summary[(seg_summary["sla_segment"] == "SLOW (>20m)") & (seg_summary["month_number"] == 1)]["retention_pct"].iloc[0])
    return {"month1_fast_retention_pct": m1_fast, "month1_slow_retention_pct": m1_slow}


def run_stockout_lost_gmv(engine, backend: str, out_dir) -> dict[str, Any]:
    """Estimate peak-hour (7 PM-10 PM IST) stockout lost GMV and lost margin without double-counting."""
    p = _table_prefix(backend)
    inv_sql = f"""
        SELECT
            ds.store_id,
            ds.store_name,
            ds.city,
            sk.sku_id,
            sk.sku_name,
            sk.category,
            fis.snapshot_timestamp,
            fis.is_stockout
        FROM {p}fact_inventory_snapshots fis
        JOIN {p}dim_dark_stores ds ON fis.store_sk = ds.store_sk
        JOIN {p}dim_skus sk ON fis.sku_sk = sk.sku_sk
    """
    inv = pd.read_sql(inv_sql, engine)
    inv["ts_utc"] = pd.to_datetime(inv["snapshot_timestamp"], utc=True)
    inv["ts_ist"] = inv["ts_utc"].dt.tz_convert("Asia/Kolkata")
    inv["hour_ist"] = inv["ts_ist"].dt.hour
    inv["is_weekend"] = (inv["ts_ist"].dt.dayofweek >= 5).astype(int)
    inv = inv.sort_values(["store_id", "sku_id", "ts_utc"]).reset_index(drop=True)

    # Non-overlapping snapshot interval capped at 15 min (0.25h)
    next_ts = inv.groupby(["store_id", "sku_id"])["ts_utc"].shift(-1)
    diff_hours = (next_ts - inv["ts_utc"]).dt.total_seconds().div(3600.0).fillna(0.25)
    inv["interval_hours"] = np.minimum(0.25, np.maximum(0.0, diff_hours))

    peak_inv = inv[inv["hour_ist"].isin([19, 20, 21])].copy()
    peak_inv["stockout_hours"] = np.where(peak_inv["is_stockout"] == 1, peak_inv["interval_hours"], 0.0)
    peak_inv["in_stock_hours"] = np.where(peak_inv["is_stockout"] == 0, peak_inv["interval_hours"], 0.0)

    inv_agg = peak_inv.groupby(["store_id", "store_name", "city", "sku_id", "sku_name", "category", "hour_ist", "is_weekend"], as_index=False).agg(
        stockout_hours=("stockout_hours", "sum"),
        in_stock_hours=("in_stock_hours", "sum"),
    )

    # Comparable peak-hour historical sales
    sales_sql = f"""
        SELECT
            ds.store_id,
            sk.sku_id,
            dt.hour_ist,
            dt.is_weekend,
            SUM(foi.quantity) AS units_sold,
            AVG(foi.historical_unit_price) AS avg_price,
            AVG(foi.historical_unit_price - foi.historical_unit_cost) AS avg_unit_margin
        FROM {p}fact_order_items foi
        JOIN {p}fact_orders fo ON foi.order_sk = fo.order_sk
        JOIN {p}dim_dark_stores ds ON fo.store_sk = ds.store_sk
        JOIN {p}dim_skus sk ON foi.sku_sk = sk.sku_sk
        JOIN {p}dim_date_time dt ON fo.date_time_sk = dt.date_time_sk
        WHERE fo.order_status = 'DELIVERED'
          AND dt.hour_ist IN (19, 20, 21)
        GROUP BY ds.store_id, sk.sku_id, dt.hour_ist, dt.is_weekend
    """
    sales = pd.read_sql(sales_sql, engine)
    sales["is_weekend"] = sales["is_weekend"].astype(int)

    merged = inv_agg.merge(sales, on=["store_id", "sku_id", "hour_ist", "is_weekend"], how="left")
    merged["units_sold"] = merged["units_sold"].fillna(0.0)
    merged["avg_price"] = merged["avg_price"].fillna(0.0)
    merged["avg_unit_margin"] = merged["avg_unit_margin"].fillna(0.0)

    # Counterfactual demand rate (units per in-stock hour) * stockout_hours * 0.75 net unfulfilled factor
    in_stock_denom = np.where(merged["in_stock_hours"] > 0.25, merged["in_stock_hours"], np.nan)
    demand_rate_per_hr = np.nan_to_num(merged["units_sold"] / in_stock_denom, nan=0.0)
    substitution_retention = 0.25  # 25% substitute to another SKU; 75% truly lost sale
    net_loss_factor = 1.0 - substitution_retention

    merged["estimated_lost_units"] = np.round(demand_rate_per_hr * merged["stockout_hours"] * net_loss_factor, 2)
    merged["estimated_lost_gmv_inr"] = np.round(merged["estimated_lost_units"] * merged["avg_price"], 2)
    merged["estimated_lost_margin_inr"] = np.round(merged["estimated_lost_units"] * merged["avg_unit_margin"], 2)

    store_sku_hour = (
        merged.groupby(["store_id", "store_name", "city", "sku_id", "sku_name", "category", "hour_ist"], as_index=False)
        .agg(
            stockout_hours=("stockout_hours", "sum"),
            in_stock_hours=("in_stock_hours", "sum"),
            observed_units_sold=("units_sold", "sum"),
            estimated_lost_units=("estimated_lost_units", "sum"),
            estimated_lost_gmv_inr=("estimated_lost_gmv_inr", "sum"),
            estimated_lost_margin_inr=("estimated_lost_margin_inr", "sum"),
        )
        .sort_values("estimated_lost_gmv_inr", ascending=False)
    )
    store_sku_hour.to_csv(out_dir / "analytics_stockout_store_sku_hour.csv", index=False)

    by_store = (
        store_sku_hour.groupby(["store_id", "store_name", "city"], as_index=False)
        .agg(
            stockout_hours=("stockout_hours", "sum"),
            estimated_lost_units=("estimated_lost_units", "sum"),
            estimated_lost_gmv_inr=("estimated_lost_gmv_inr", "sum"),
            estimated_lost_margin_inr=("estimated_lost_margin_inr", "sum"),
        )
        .sort_values("estimated_lost_gmv_inr", ascending=False)
    )
    by_store.to_csv(out_dir / "analytics_stockout_by_store.csv", index=False)

    by_sku = (
        store_sku_hour.groupby(["sku_id", "sku_name", "category"], as_index=False)
        .agg(
            stockout_hours=("stockout_hours", "sum"),
            estimated_lost_units=("estimated_lost_units", "sum"),
            estimated_lost_gmv_inr=("estimated_lost_gmv_inr", "sum"),
            estimated_lost_margin_inr=("estimated_lost_margin_inr", "sum"),
        )
        .sort_values("estimated_lost_gmv_inr", ascending=False)
    )
    by_sku.to_csv(out_dir / "analytics_stockout_by_sku.csv", index=False)

    return {
        "total_peak_stockout_hours": round(float(store_sku_hour["stockout_hours"].sum()), 2),
        "estimated_lost_units": round(float(store_sku_hour["estimated_lost_units"].sum()), 2),
        "estimated_lost_gmv_inr": round(float(store_sku_hour["estimated_lost_gmv_inr"].sum()), 2),
        "estimated_lost_margin_inr": round(float(store_sku_hour["estimated_lost_margin_inr"].sum()), 2),
    }


def run_store_ranking(out_dir) -> pd.DataFrame:
    """Combine store unit economics, SLA, and stockout losses to rank stores and derive root-cause tags."""
    ncm = pd.read_csv(out_dir / "analytics_ncm_by_store.csv")
    sla = pd.read_csv(out_dir / "analytics_sla_by_store.csv")
    stk = pd.read_csv(out_dir / "analytics_stockout_by_store.csv")

    merged = (
        ncm.merge(sla[["store_id", "delivered_orders", "avg_delivery_min", "p90_delivery_min", "avg_picking_min", "avg_assignment_min", "avg_transit_min", "sla_breach_pct", "primary_bottleneck"]], on="store_id", how="left")
        .merge(stk[["store_id", "estimated_lost_gmv_inr", "estimated_lost_margin_inr"]], on="store_id", how="left")
    )
    merged["estimated_lost_gmv_inr"] = merged["estimated_lost_gmv_inr"].fillna(0.0)
    merged["estimated_lost_margin_inr"] = merged["estimated_lost_margin_inr"].fillna(0.0)

    stk_p75 = float(np.percentile(merged["estimated_lost_gmv_inr"], 75))
    rider_p75 = float(np.percentile(merged["avg_rider_payout_inr"], 75))
    disc_p75 = float(np.percentile(merged["discount_pct_of_gmv"], 75))
    ref_p75 = float(np.percentile(merged["avg_refund_inr"], 75))

    def _derive_tags(r) -> str:
        tags = []
        if r["avg_rider_payout_inr"] >= max(36.0, rider_p75):
            tags.append("HIGH_RIDER_COST")
        if r["avg_picking_min"] > 3.8:
            tags.append("PICKING_BOTTLENECK")
        if r["avg_assignment_min"] > 3.0:
            tags.append("RIDER_SHORTAGE")
        if r["avg_transit_min"] > 7.2:
            tags.append("TRANSIT_DELAY")
        if r["discount_pct_of_gmv"] >= max(10.5, disc_p75):
            tags.append("HIGH_DISCOUNT_BURN")
        if r["estimated_lost_gmv_inr"] >= stk_p75 and r["estimated_lost_gmv_inr"] > 0:
            tags.append("STOCKOUT_LOSS")
        if r["avg_refund_inr"] >= max(3.5, ref_p75):
            tags.append("HIGH_REFUND_COST")
        return ", ".join(tags) if tags else "HEALTHY_OPERATIONS"

    merged["root_cause_tags"] = merged.apply(_derive_tags, axis=1)
    merged["profitability_rank"] = merged["avg_ncm_per_order_inr"].rank(ascending=False, method="min").astype(int)
    merged["sla_rank"] = merged["sla_breach_pct"].rank(ascending=True, method="min").astype(int)
    merged["efficiency_score"] = np.round(
        (merged["avg_ncm_per_order_inr"].rank(pct=True) * 0.60)
        + ((100.0 - merged["sla_breach_pct"]).rank(pct=True) * 0.40),
        3,
    )
    merged = merged.sort_values("avg_ncm_per_order_inr", ascending=True)
    merged.to_csv(out_dir / "analytics_store_ranking_root_cause.csv", index=False)
    return merged


def run_all_analytics() -> dict[str, Any]:
    """Execute all Phase 5 analytical modules and write summary JSON."""
    out_dir = PROJECT_ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    engine, backend = get_engine(allow_sqlite_fallback=True)

    logger.info("Running Unit Economics analytics...")
    ue_summary = run_unit_economics(engine, backend, out_dir)

    logger.info("Running Delivery SLA & Bottleneck analytics...")
    sla_summary = run_sla_analysis(engine, backend, out_dir)

    logger.info("Running Customer Cohort Retention analytics...")
    cohort_summary = run_cohort_retention(engine, backend, out_dir)

    logger.info("Running Peak-Hour Stockout Lost GMV analytics...")
    stockout_summary = run_stockout_lost_gmv(engine, backend, out_dir)

    logger.info("Running Store Performance Ranking & Root-Cause diagnostics...")
    ranking_df = run_store_ranking(out_dir)

    summary = {
        "unit_economics": ue_summary,
        "sla": sla_summary,
        "cohort_retention": cohort_summary,
        "stockout_lost_gmv": stockout_summary,
        "bottom_5_stores": ranking_df.head(5)[["store_id", "store_name", "city", "avg_ncm_per_order_inr", "sla_breach_pct", "primary_bottleneck", "root_cause_tags"]].to_dict(orient="records"),
    }
    summary_path = PROJECT_ROOT / "reports" / "analytics_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    logger.info("All Core Business Analytics complete. Summary saved to %s", summary_path)
    return summary


if __name__ == "__main__":
    res = run_all_analytics()
    print(json.dumps(res, indent=2))
