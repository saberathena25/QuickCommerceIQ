"""Unit and integration tests for SLA decomposition, bottlenecks, and stockout lost GMV."""

import pandas as pd

from python.config import PROJECT_ROOT


def test_sla_stage_decomposition_sums_to_total():
    proc_orders = PROJECT_ROOT / "data" / "processed" / "fact_orders_clean.csv"
    df = pd.read_csv(proc_orders)
    deliv = df[df["order_status"] == "DELIVERED"].head(5000)
    stage_sum = deliv["picking_seconds"] + deliv["assignment_seconds"] + deliv["transit_seconds"]
    assert (stage_sum - deliv["total_delivery_seconds"]).abs().max() == 0
    assert (deliv["picking_seconds"] >= 0).all()
    assert (deliv["assignment_seconds"] >= 0).all()
    assert (deliv["transit_seconds"] >= 0).all()


def test_sla_breach_flag_matches_12_min_threshold():
    proc_orders = PROJECT_ROOT / "data" / "processed" / "fact_orders_clean.csv"
    df = pd.read_csv(proc_orders)
    deliv = df[df["order_status"] == "DELIVERED"]
    expected_breach = deliv["total_delivery_seconds"] > 720
    assert (deliv["is_sla_breach"] == expected_breach).all()


def test_stockout_lost_gmv_non_negative_and_no_overcount():
    stk = pd.read_csv(PROJECT_ROOT / "data" / "processed" / "analytics_stockout_store_sku_hour.csv")
    assert not stk.empty
    assert (stk["hour_ist"].isin([19, 20, 21])).all()
    assert (stk["stockout_hours"] >= 0).all()
    assert (stk["estimated_lost_gmv_inr"] >= 0).all()
    # 184 days * 1h per hour_ist slot = max 184 hours per store-sku-hour
    assert (stk["stockout_hours"] <= 184.0).all()
