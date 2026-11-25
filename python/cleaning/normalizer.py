"""Normalization functions: text cleanup, city/payment mapping, UTC/IST timestamps, deduplication."""

from __future__ import annotations

import re
from typing import Tuple

import pandas as pd

from python.config import get_city_mapping, get_logger

logger = get_logger(__name__)


def normalize_text_series(s: pd.Series) -> pd.Series:
    """Strip whitespace and collapse internal spacing while preserving nulls."""
    return s.where(s.isna(), s.astype(str).str.strip().str.replace(r"\s+", " ", regex=True))


def normalize_cities(df: pd.DataFrame, col: str = "city") -> pd.DataFrame:
    """Normalize inconsistent city spellings (e.g. Bangalore -> Bengaluru, Bombay -> Mumbai)."""
    out = df.copy()
    city_map = get_city_mapping()["city_aliases"]
    cleaned = normalize_text_series(out[col])
    out[col] = cleaned.map(lambda x: city_map.get(str(x).lower(), x) if pd.notna(x) else x)
    return out


def normalize_payment_modes(df: pd.DataFrame, col: str = "payment_mode") -> pd.DataFrame:
    """Standardize payment mode aliases (gpay/phonepe -> UPI, credit_card -> CARD, cash -> COD)."""
    out = df.copy()
    pay_map = get_city_mapping()["payment_mode_aliases"]
    cleaned = normalize_text_series(out[col])
    out[col] = cleaned.map(lambda x: pay_map.get(str(x).lower(), str(x).upper()) if pd.notna(x) else x)
    return out


def validate_indian_pincode(pincode: object, city: object = None) -> bool:
    """Validate 6-digit Indian pincode format and optional city prefix match."""
    if pd.isna(pincode):
        return False
    pin_str = str(pincode).strip()
    if not re.match(r"^\d{6}$", pin_str):
        return False
    if city is not None and not pd.isna(city):
        canonical = get_city_mapping()["canonical_cities"]
        if str(city) in canonical:
            regex = canonical[str(city)]["valid_pincode_regex"]
            return bool(re.match(regex, pin_str))
    return True


def standardize_timestamps_to_utc(df: pd.DataFrame, ts_columns: list[str]) -> pd.DataFrame:
    """Parse mixed UTC/IST ISO timestamps and normalize all to UTC."""
    out = df.copy()
    for col in ts_columns:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], format="mixed", utc=True, errors="coerce")
    return out


def to_ist_series(utc_series: pd.Series) -> pd.Series:
    """Convert a UTC datetime64 series to Asia/Kolkata timezone."""
    dt = pd.to_datetime(utc_series, utc=True, errors="coerce")
    return dt.dt.tz_convert("Asia/Kolkata")


def deduplicate_by_key(
    df: pd.DataFrame,
    key_col: str,
    sort_col: str | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Remove duplicate business-key events, returning (deduplicated_df, duplicates_df)."""
    work = df.copy()
    if sort_col and sort_col in work.columns:
        work = work.sort_values(sort_col, kind="mergesort")
    dup_mask = work.duplicated(subset=[key_col], keep="first")
    duplicates = work[dup_mask].copy()
    deduped = work[~dup_mask].copy()
    logger.info(
        "Deduplicated on %s: kept=%d, dropped_duplicates=%d",
        key_col, len(deduped), len(duplicates),
    )
    return deduped, duplicates
