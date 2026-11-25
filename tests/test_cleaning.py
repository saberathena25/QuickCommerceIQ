"""Unit tests for data normalization, deduplication, timestamp conversion, and pincode checks."""

import pandas as pd

from python.cleaning.normalizer import (
    deduplicate_by_key,
    normalize_cities,
    normalize_payment_modes,
    standardize_timestamps_to_utc,
    to_ist_series,
    validate_indian_pincode,
)


def test_city_normalization():
    df = pd.DataFrame({"city": ["Bangalore", "bombay", "New Delhi", "Madras", "Bengaluru"]})
    out = normalize_cities(df)
    assert out["city"].tolist() == ["Bengaluru", "Mumbai", "Delhi NCR", "Chennai", "Bengaluru"]


def test_payment_mode_normalization():
    df = pd.DataFrame({"payment_mode": ["gpay", "phonepe", "credit_card", "cash_on_delivery", "UPI"]})
    out = normalize_payment_modes(df)
    assert out["payment_mode"].tolist() == ["UPI", "UPI", "CARD", "COD", "UPI"]


def test_indian_pincode_validation():
    assert validate_indian_pincode("560034", "Bengaluru") is True
    assert validate_indian_pincode("400050", "Mumbai") is True
    assert validate_indian_pincode("122001", "Delhi NCR") is True
    assert validate_indian_pincode("600006", "Chennai") is True
    assert validate_indian_pincode("5600A1", "Bengaluru") is False
    assert validate_indian_pincode("400050", "Bengaluru") is False


def test_timestamp_utc_and_ist_roundtrip():
    df = pd.DataFrame({
        "placed_at": [
            "2026-06-15T14:30:00Z",
            "2026-06-15 20:00:00+05:30",
        ]
    })
    utc_df = standardize_timestamps_to_utc(df, ["placed_at"])
    ist = to_ist_series(utc_df["placed_at"])
    assert ist.dt.hour.tolist() == [20, 20]
    assert ist.dt.minute.tolist() == [0, 0]


def test_deduplication_keeps_first():
    df = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-1", "ORD-2"],
        "placed_at": ["2026-05-01T10:00:00Z", "2026-05-01T10:00:05Z", "2026-05-01T11:00:00Z"],
    })
    deduped, dups = deduplicate_by_key(df, "order_id", sort_col="placed_at")
    assert len(deduped) == 2
    assert len(dups) == 1
    assert dups.iloc[0]["order_id"] == "ORD-1"
