"""Automated data quality tests: null validation, cancelled preservation, reconciliation, and gate enforcement."""

import json

import pandas as pd
import pytest

from data_quality.quality_checks import (
    DataQualityGateError,
    clean_and_validate_orders,
    evaluate_quality_gates_and_report,
    load_validation_rules,
)
from data_quality.quarantine import QuarantineManager
from python.config import PROJECT_ROOT


def test_cancelled_orders_not_rejected_for_null_delivered_at():
    raw = pd.DataFrame([
        {
            "order_id": "ORD-CANC-1",
            "customer_id": "CUST-000001",
            "store_id": "STR-001",
            "rider_id": None,
            "placed_at": "2026-06-01T10:00:00Z",
            "packed_at": "2026-06-01T10:02:00Z",
            "dispatched_at": None,
            "delivered_at": None,
            "cancelled_at": "2026-06-01T10:03:00Z",
            "order_status": "CANCELLED",
            "payment_mode": "UPI",
            "cart_value": 250.0,
            "discounts": 0.0,
            "delivery_fee": 0.0,
            "handling_fee": 0.0,
            "surge_fee": 0.0,
            "gross_margin": 0.0,
            "rider_payout": 8.0,
            "packaging_cost": 2.0,
            "refund_cost": 0.0,
            "weather_tag": "NORMAL",
        }
    ])
    qm = QuarantineManager("TEST-BATCH")
    rules = load_validation_rules()
    acc, stats = clean_and_validate_orders(
        raw, {"STR-001"}, {"CUST-000001"}, {"RDR-0001"}, qm, rules
    )
    assert stats["accepted_count"] == 1
    assert acc.iloc[0]["order_status"] == "CANCELLED"


def test_invalid_lifecycle_and_negative_cart_quarantined():
    raw = pd.DataFrame([
        {
            "order_id": "ORD-BAD-LIFE",
            "customer_id": "CUST-000001",
            "store_id": "STR-001",
            "rider_id": "RDR-0001",
            "placed_at": "2026-06-01T10:10:00Z",
            "packed_at": "2026-06-01T10:12:00Z",
            "dispatched_at": "2026-06-01T10:14:00Z",
            "delivered_at": "2026-06-01T10:05:00Z",  # Before placed_at!
            "cancelled_at": None,
            "order_status": "DELIVERED",
            "payment_mode": "UPI",
            "cart_value": 250.0,
            "discounts": 10.0,
            "delivery_fee": 0.0,
            "handling_fee": 5.0,
            "surge_fee": 0.0,
            "gross_margin": 55.0,
            "rider_payout": 30.0,
            "packaging_cost": 6.0,
            "refund_cost": 0.0,
            "weather_tag": "NORMAL",
        }
    ])
    qm = QuarantineManager("TEST-BATCH-2")
    rules = load_validation_rules()
    acc, stats = clean_and_validate_orders(
        raw, {"STR-001"}, {"CUST-000001"}, {"RDR-0001"}, qm, rules
    )
    assert stats["accepted_count"] == 0
    assert stats["rejected_validation"] == 1
    assert qm.to_dataframe().iloc[0]["rejection_reason"] == "INVALID_LIFECYCLE_SEQUENCE"


def test_pipeline_data_quality_report_reconciliation_and_pass():
    report_path = PROJECT_ROOT / "reports" / "data_quality_report.json"
    assert report_path.exists()
    with report_path.open("r", encoding="utf-8") as fh:
        rep = json.load(fh)
    assert rep["quality_gate_passed"] is True
    assert all(rep["gates"].values())
    m_ord = rep["metrics"]["orders"]
    assert m_ord["accepted_count"] >= 150000
    assert m_ord["raw_count"] == (
        m_ord["accepted_count"] + m_ord["duplicates_dropped"] + m_ord["rejected_validation"]
    )


def test_critical_gate_raises_on_pk_duplicate(tmp_path):
    qm = QuarantineManager("TEST-FAIL")
    dup_orders = pd.DataFrame({"order_id": ["O1", "O1"], "store_id": ["S1", "S1"], "order_status": ["DELIVERED", "DELIVERED"]})
    items = pd.DataFrame({"order_item_id": ["I1"], "order_id": ["O1"]})
    stores = pd.DataFrame({"store_id": ["S1"]})
    with pytest.raises(DataQualityGateError):
        evaluate_quality_gates_and_report(
            batch_id="TEST-FAIL",
            order_stats={"raw_count": 2, "duplicates_dropped": 0, "rejected_validation": 0, "accepted_count": 2},
            item_stats={"raw_count": 1, "duplicates_dropped": 0, "rejected_validation": 0, "accepted_count": 1},
            inv_stats={"raw_count": 0, "duplicates_dropped": 0, "rejected_validation": 0, "accepted_count": 0},
            orders_acc=dup_orders,
            items_acc=items,
            stores_acc=stores,
            qm=qm,
            strict=True,
            report_path=tmp_path / "dq_fail.json",
        )
