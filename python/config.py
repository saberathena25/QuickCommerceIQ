"""Shared configuration, path resolution, logging, and INR formatting utilities for QuickCommerceIQ."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


def get_logger(name: str) -> logging.Logger:
    """Create or retrieve a configured module logger."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def load_yaml(relative_path: str) -> dict[str, Any]:
    """Load a YAML configuration file relative to PROJECT_ROOT."""
    path = PROJECT_ROOT / relative_path
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(relative_path: str) -> dict[str, Any]:
    """Load a JSON configuration file relative to PROJECT_ROOT."""
    path = PROJECT_ROOT / relative_path
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get_settings() -> dict[str, Any]:
    return load_yaml("config/settings.yaml")


def get_simulation_config() -> dict[str, Any]:
    return load_yaml("config/simulation_config.yaml")


def get_city_mapping() -> dict[str, Any]:
    return load_json("config/city_mapping.json")


def ensure_project_dirs() -> None:
    """Create expected project directories if missing."""
    dirs = [
        "data/raw",
        "data/staging",
        "data/processed",
        "data/sample",
        "sql/ddl",
        "sql/transformations",
        "sql/analytics",
        "python/generators",
        "python/ingestion",
        "python/cleaning",
        "python/analytics",
        "python/experiments",
        "data_quality",
        "excel_models",
        "dashboard",
        "tests",
        "docs",
        "reports",
    ]
    for d in dirs:
        (PROJECT_ROOT / d).mkdir(parents=True, exist_ok=True)


def format_inr(amount: float, decimals: int = 2) -> str:
    """Format a numeric amount using Indian numbering (lakhs/crores) and INR symbol."""
    sign = "-" if amount < 0 else ""
    val = abs(float(amount))
    if val >= 1_00_00_000:
        return f"{sign}₹{val / 1_00_00_000:,.2f} Crore"
    if val >= 1_00_000:
        return f"{sign}₹{val / 1_00_000:,.2f} Lakhs"
    integer_part = int(val)
    frac_part = f"{val - integer_part:.{decimals}f}"[1:] if decimals > 0 else ""
    s = str(integer_part)
    if len(s) <= 3:
        formatted = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.append(rest)
        formatted = ",".join(reversed(groups)) + "," + last3
    return f"{sign}₹{formatted}{frac_part}"
