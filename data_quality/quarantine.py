"""Anomaly quarantine management for rejected/malformed operational records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from python.config import PROJECT_ROOT, get_logger

logger = get_logger(__name__)


class QuarantineManager:
    """Collects quarantined records across ETL entities and persists CSV + DB audit records."""

    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        self.records: list[dict[str, Any]] = []

    def add_dataframe(
        self,
        df: pd.DataFrame,
        entity_type: str,
        key_col: str | None,
        reason: str,
        severity: str = "ERROR",
    ) -> None:
        """Quarantine all rows in a DataFrame slice with a specific rejection reason."""
        if df.empty:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        payloads = df.astype(object).where(pd.notna(df), None).to_dict(orient="records")
        for row in payloads:
            bkey = str(row.get(key_col)) if key_col and row.get(key_col) is not None else None
            self.records.append({
                "batch_id": self.batch_id,
                "entity_type": entity_type,
                "business_key": bkey,
                "rejection_reason": reason,
                "severity": severity,
                "raw_payload": json.dumps(row, default=str),
                "quarantined_at": now_iso,
            })
        logger.info("Quarantined %d %s rows (%s)", len(df), entity_type, reason)

    def to_dataframe(self) -> pd.DataFrame:
        if not self.records:
            return pd.DataFrame(
                columns=[
                    "batch_id",
                    "entity_type",
                    "business_key",
                    "rejection_reason",
                    "severity",
                    "raw_payload",
                    "quarantined_at",
                ]
            )
        return pd.DataFrame(self.records)

    def summary_counts(self) -> dict[str, dict[str, int]]:
        df = self.to_dataframe()
        if df.empty:
            return {}
        summary: dict[str, dict[str, int]] = {}
        for (entity, reason), grp in df.groupby(["entity_type", "rejection_reason"]):
            summary.setdefault(str(entity), {})[str(reason)] = int(len(grp))
        return summary

    def write_staging_csv(self) -> str:
        out_path = PROJECT_ROOT / "data" / "staging" / "quarantined_anomalies.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self.to_dataframe().to_csv(out_path, index=False)
        return str(out_path)
