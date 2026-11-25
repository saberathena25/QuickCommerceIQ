"""Automated data validation rules, reconciliation checks, and quality gate enforcement."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple

import numpy as np
import pandas as pd

from data_quality.quarantine import QuarantineManager
from python.cleaning.normalizer import (
    deduplicate_by_key,
    normalize_cities,
    normalize_payment_modes,
    standardize_timestamps_to_utc,
    validate_indian_pincode,
)
from python.config import PROJECT_ROOT, get_logger, load_yaml

logger = get_logger(__name__)


class DataQualityGateError(RuntimeError):
    """Raised when a critical data quality gate fails and blocks warehouse publication."""


def load_validation_rules() -> dict[str, Any]:
    return load_yaml("data_quality/validation_rules.yaml")


def clean_and_validate_stores(
    raw_stores: pd.DataFrame,
    qm: QuarantineManager,
) -> pd.DataFrame:
    """Normalize store cities and quarantine malformed pincodes."""
    df = normalize_cities(raw_stores, col="city")
    df, dups = deduplicate_by_key(df, "store_id")
    qm.add_dataframe(dups, "dark_stores", "store_id", "DUPLICATE_STORE_ID", severity="WARNING")

    valid_pin = df.apply(lambda r: validate_indian_pincode(r["pincode"], r["city"]), axis=1)
    bad_pin = df[~valid_pin]
    qm.add_dataframe(bad_pin, "dark_stores", "store_id", "INVALID_INDIAN_PINCODE")
    accepted = df[valid_pin].copy()
    return accepted.reset_index(drop=True)


def clean_and_validate_orders(
    raw_orders: pd.DataFrame,
    valid_store_ids: set[str],
    valid_customer_ids: set[str],
    valid_rider_ids: set[str],
    qm: QuarantineManager,
    rules: dict[str, Any],
) -> Tuple[pd.DataFrame, dict[str, int]]:
    """Clean, deduplicate, timezone-normalize, and validate orders without dropping cancelled orders."""
    order_rules = rules["rules"]["orders"]
    raw_count = len(raw_orders)

    df = normalize_payment_modes(raw_orders, col="payment_mode")
    df = standardize_timestamps_to_utc(
        df,
        ["placed_at", "packed_at", "dispatched_at", "delivered_at", "cancelled_at"],
    )

    # 1. Deduplicate webhook & notification duplicates
    df, dups = deduplicate_by_key(df, "order_id", sort_col="placed_at")
    qm.add_dataframe(dups, "orders", "order_id", "DUPLICATE_WEBHOOK_OR_NOTIFICATION", severity="WARNING")

    reject_mask = pd.Series(False, index=df.index)
    reason_series = pd.Series("", index=df.index)

    def _flag(cond: pd.Series, reason: str) -> None:
        nonlocal reject_mask, reason_series
        newly_flagged = cond & (~reject_mask)
        if newly_flagged.any():
            qm.add_dataframe(df[newly_flagged], "orders", "order_id", reason)
            reject_mask = reject_mask | newly_flagged
            reason_series = reason_series.where(~newly_flagged, reason)

    # 2. Required non-null fields
    for col in order_rules["required_non_null"]:
        _flag(df[col].isna(), f"MISSING_REQUIRED_{col.upper()}")

    # 3. Domain checks
    _flag(~df["order_status"].isin(order_rules["valid_statuses"]), "INVALID_ORDER_STATUS")
    _flag(~df["payment_mode"].isin(order_rules["valid_payment_modes"]), "INVALID_PAYMENT_MODE")
    _flag(~df["weather_tag"].isin(order_rules["valid_weather_tags"]), "INVALID_WEATHER_TAG")

    # 4. Financial non-negative checks
    for num_col in order_rules["numeric_non_negative"]:
        df[num_col] = pd.to_numeric(df[num_col], errors="coerce")
        _flag(df[num_col].isna() | (df[num_col] < 0), f"NEGATIVE_OR_INVALID_{num_col.upper()}")

    # 5. Lifecycle validation (CANCELLED orders are allowed NULL delivered_at / dispatched_at / rider_id)
    is_deliv = df["order_status"] == "DELIVERED"
    for col in order_rules["lifecycle_checks"]["delivered_must_have"]:
        _flag(is_deliv & df[col].isna(), f"DELIVERED_MISSING_{col.upper()}")

    # Monotonic sequence checks
    bad_pack = df["packed_at"].notna() & (df["packed_at"] < df["placed_at"])
    bad_disp = df["dispatched_at"].notna() & (
        df["packed_at"].isna() | (df["dispatched_at"] < df["packed_at"])
    )
    bad_deliv = df["delivered_at"].notna() & (
        df["dispatched_at"].isna() | (df["delivered_at"] < df["dispatched_at"])
    )
    _flag(bad_pack | bad_disp | bad_deliv, "INVALID_LIFECYCLE_SEQUENCE")

    # 6. Referential integrity
    _flag(~df["store_id"].isin(valid_store_ids), "ORPHAN_STORE_ID")
    _flag(~df["customer_id"].isin(valid_customer_ids), "ORPHAN_CUSTOMER_ID")
    _flag(df["rider_id"].notna() & (~df["rider_id"].isin(valid_rider_ids)), "ORPHAN_RIDER_ID")

    accepted = df[~reject_mask].copy().reset_index(drop=True)

    # Derived financial & SLA columns
    accepted["net_contribution_margin"] = np.round(
        accepted["gross_margin"]
        + accepted["handling_fee"]
        + accepted["delivery_fee"]
        + accepted["surge_fee"]
        - accepted["discounts"]
        - accepted["rider_payout"]
        - accepted["packaging_cost"]
        - accepted["refund_cost"],
        2,
    )
    accepted["picking_seconds"] = np.where(
        accepted["packed_at"].notna(),
        (accepted["packed_at"] - accepted["placed_at"]).dt.total_seconds(),
        np.nan,
    )
    accepted["assignment_seconds"] = np.where(
        accepted["dispatched_at"].notna() & accepted["packed_at"].notna(),
        (accepted["dispatched_at"] - accepted["packed_at"]).dt.total_seconds(),
        np.nan,
    )
    accepted["transit_seconds"] = np.where(
        accepted["delivered_at"].notna() & accepted["dispatched_at"].notna(),
        (accepted["delivered_at"] - accepted["dispatched_at"]).dt.total_seconds(),
        np.nan,
    )
    accepted["total_delivery_seconds"] = np.where(
        accepted["delivered_at"].notna(),
        (accepted["delivered_at"] - accepted["placed_at"]).dt.total_seconds(),
        np.nan,
    )
    accepted["is_sla_breach"] = (
        (accepted["order_status"] == "DELIVERED")
        & (accepted["total_delivery_seconds"] > 12 * 60)
    )

    stats = {
        "raw_count": raw_count,
        "duplicates_dropped": len(dups),
        "rejected_validation": int(reject_mask.sum()),
        "accepted_count": len(accepted),
    }
    return accepted, stats


def clean_and_validate_order_items(
    raw_items: pd.DataFrame,
    accepted_order_ids: set[str],
    valid_sku_ids: set[str],
    qm: QuarantineManager,
) -> Tuple[pd.DataFrame, dict[str, int]]:
    """Validate order items: positive prices/costs/qty and referential integrity to orders & SKUs."""
    raw_count = len(raw_items)
    df, dups = deduplicate_by_key(raw_items, "order_item_id")
    qm.add_dataframe(dups, "order_items", "order_item_id", "DUPLICATE_ORDER_ITEM_ID", severity="WARNING")

    for col in ["quantity", "unit_price", "unit_cost"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    bad_vals = (
        df["quantity"].isna() | (df["quantity"] <= 0)
        | df["unit_price"].isna() | (df["unit_price"] <= 0)
        | df["unit_cost"].isna() | (df["unit_cost"] <= 0)
    )
    bad_order_fk = ~df["order_id"].isin(accepted_order_ids)
    bad_sku_fk = ~df["sku_id"].isin(valid_sku_ids)

    qm.add_dataframe(df[bad_vals], "order_items", "order_item_id", "NEGATIVE_OR_INVALID_PRICE_COST_QTY")
    qm.add_dataframe(df[~bad_vals & bad_sku_fk], "order_items", "order_item_id", "INVALID_SKU_REFERENCE")
    qm.add_dataframe(
        df[~bad_vals & ~bad_sku_fk & bad_order_fk],
        "order_items",
        "order_item_id",
        "ORPHAN_ORDER_REFERENCE",
        severity="WARNING",
    )

    keep = (~bad_vals) & (~bad_sku_fk) & (~bad_order_fk)
    accepted = df[keep].copy().reset_index(drop=True)
    accepted["line_total"] = np.round(accepted["quantity"] * accepted["unit_price"], 2)
    accepted["line_gross_margin"] = np.round(
        accepted["quantity"] * (accepted["unit_price"] - accepted["unit_cost"]), 2
    )

    stats = {
        "raw_count": raw_count,
        "duplicates_dropped": len(dups),
        "rejected_validation": int((~keep).sum()),
        "accepted_count": len(accepted),
    }
    return accepted, stats


def clean_and_validate_inventory(
    raw_inv: pd.DataFrame,
    valid_store_ids: set[str],
    valid_sku_ids: set[str],
    qm: QuarantineManager,
) -> Tuple[pd.DataFrame, dict[str, int]]:
    """Quarantine negative inventory glitches and standardize snapshot timestamps to UTC."""
    raw_count = len(raw_inv)
    df = standardize_timestamps_to_utc(raw_inv, ["snapshot_timestamp"])
    df, dups = deduplicate_by_key(df, "snapshot_id")
    qm.add_dataframe(dups, "inventory_snapshots", "snapshot_id", "DUPLICATE_SNAPSHOT_ID", severity="WARNING")

    df["stock_on_hand"] = pd.to_numeric(df["stock_on_hand"], errors="coerce")
    bad_neg = df["stock_on_hand"].isna() | (df["stock_on_hand"] < 0)
    bad_fk = (~df["store_id"].isin(valid_store_ids)) | (~df["sku_id"].isin(valid_sku_ids))

    qm.add_dataframe(df[bad_neg], "inventory_snapshots", "snapshot_id", "NEGATIVE_INVENTORY_GLITCH")
    qm.add_dataframe(df[~bad_neg & bad_fk], "inventory_snapshots", "snapshot_id", "ORPHAN_STORE_OR_SKU")

    keep = (~bad_neg) & (~bad_fk) & df["snapshot_timestamp"].notna()
    accepted = df[keep].copy().reset_index(drop=True)
    accepted["stock_on_hand"] = accepted["stock_on_hand"].astype(int)
    accepted["is_stockout"] = accepted["stock_on_hand"] == 0

    stats = {
        "raw_count": raw_count,
        "duplicates_dropped": len(dups),
        "rejected_validation": int((~keep).sum()),
        "accepted_count": len(accepted),
    }
    return accepted, stats


def evaluate_quality_gates_and_report(
    batch_id: str,
    order_stats: dict[str, int],
    item_stats: dict[str, int],
    inv_stats: dict[str, int],
    orders_acc: pd.DataFrame,
    items_acc: pd.DataFrame,
    stores_acc: pd.DataFrame,
    qm: QuarantineManager,
    strict: bool = True,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Run critical warehouse quality gates and write reports/data_quality_report.json."""
    rules = load_validation_rules()
    max_rej_pct = float(rules["critical_gates"]["max_rejection_rate_pct"])

    # Reconciliation assertions
    ord_reconciled = (
        order_stats["raw_count"]
        == order_stats["accepted_count"] + order_stats["duplicates_dropped"] + order_stats["rejected_validation"]
    )
    item_reconciled = (
        item_stats["raw_count"]
        == item_stats["accepted_count"] + item_stats["duplicates_dropped"] + item_stats["rejected_validation"]
    )
    inv_reconciled = (
        inv_stats["raw_count"]
        == inv_stats["accepted_count"] + inv_stats["duplicates_dropped"] + inv_stats["rejected_validation"]
    )

    pk_dups_orders = int(orders_acc["order_id"].duplicated().sum())
    pk_dups_items = int(items_acc["order_item_id"].duplicated().sum())
    orphan_items = int((~items_acc["order_id"].isin(set(orders_acc["order_id"]))).sum())
    orphan_stores = int((~orders_acc["store_id"].isin(set(stores_acc["store_id"]))).sum())
    cancelled_kept = int((orders_acc["order_status"] == "CANCELLED").sum())

    order_rej_pct = round(
        100.0 * (order_stats["duplicates_dropped"] + order_stats["rejected_validation"]) / max(1, order_stats["raw_count"]),
        2,
    )

    gates = {
        "order_reconciliation_exact": ord_reconciled,
        "item_reconciliation_exact": item_reconciled,
        "inventory_reconciliation_exact": inv_reconciled,
        "zero_pk_duplicates": (pk_dups_orders == 0 and pk_dups_items == 0),
        "referential_integrity_clean": (orphan_items == 0 and orphan_stores == 0),
        "cancelled_orders_preserved": cancelled_kept > 0,
        "rejection_rate_within_threshold": order_rej_pct <= max_rej_pct,
    }
    all_passed = all(gates.values())

    report = {
        "batch_id": batch_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "quality_gate_passed": all_passed,
        "gates": gates,
        "metrics": {
            "orders": {**order_stats, "rejection_and_dup_pct": order_rej_pct, "cancelled_orders_accepted": cancelled_kept},
            "order_items": item_stats,
            "inventory_snapshots": inv_stats,
            "accepted_stores": len(stores_acc),
        },
        "quarantine_breakdown": qm.summary_counts(),
    }

    if report_path is None:
        report_path = PROJECT_ROOT / "reports" / "data_quality_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    if strict and not all_passed:
        raise DataQualityGateError(f"Critical data quality gate failed: {gates}")

    logger.info("Data quality gate PASSED. Report saved to %s", report_path)
    return report
