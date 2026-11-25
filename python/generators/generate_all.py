"""Main synthetic data generation entrypoint for QuickCommerceIQ."""

from __future__ import annotations

import numpy as np
import pandas as pd

from python.config import PROJECT_ROOT, ensure_project_dirs, get_logger, get_simulation_config
from python.generators.master_data import (
    generate_customers,
    generate_dark_stores,
    generate_riders,
    generate_skus,
    generate_weather_data,
)
from python.generators.orders_and_telemetry import (
    generate_inventory_snapshots,
    generate_orders_and_items,
    generate_rider_logs,
    inject_messy_data,
)

logger = get_logger(__name__)


def run_data_generation(seed: int | None = None) -> dict[str, int]:
    """Generate all 11 raw synthetic CSVs (plus SCD2 histories and sample files) reproducibly."""
    ensure_project_dirs()
    sim_cfg = get_simulation_config()
    used_seed = int(seed if seed is not None else sim_cfg["seed"])
    rng = np.random.default_rng(used_seed)

    raw_dir = PROJECT_ROOT / "data" / "raw"
    sample_dir = PROJECT_ROOT / "data" / "sample"

    logger.info("Starting QuickCommerceIQ synthetic data generation (seed=%d)...", used_seed)

    stores_df, stores_scd_df = generate_dark_stores(rng)
    skus_df, skus_scd_df = generate_skus(rng, n_skus=int(sim_cfg["scale"]["skus"]))
    riders_df = generate_riders(rng, stores_df, n_riders=int(sim_cfg["scale"]["riders"]))
    customers_df = generate_customers(rng, stores_df, n_customers=int(sim_cfg["scale"]["customers"]))
    weather_df = generate_weather_data(rng)

    orders_df, order_items_df, ab_assign_df, ab_events_df = generate_orders_and_items(
        rng=rng,
        stores_df=stores_df,
        stores_scd_df=stores_scd_df,
        skus_df=skus_df,
        skus_scd_df=skus_scd_df,
        customers_df=customers_df,
        riders_df=riders_df,
        weather_df=weather_df,
    )

    # Refresh customer first_order_date in customers_df using clean delivered orders before messy injection
    # Inject city spelling typos into ~2% of customers for cleaning pipeline testing
    cust_raw = customers_df.copy()
    typo_idx = rng.choice(len(cust_raw), size=int(len(cust_raw) * 0.02), replace=False)
    city_typos = {"Bengaluru": "Bangalore", "Mumbai": "Bombay", "Delhi NCR": "Gurgaon", "Chennai": "Madras"}
    cust_raw.loc[typo_idx, "city"] = cust_raw.loc[typo_idx, "city"].map(lambda c: city_typos.get(c, c))

    inv_df = generate_inventory_snapshots(rng, stores_df, skus_df)
    rider_logs_df = generate_rider_logs(rng, orders_df)

    # Inject controlled messy data anomalies into raw tables
    raw_stores, raw_orders, raw_items, raw_inv = inject_messy_data(
        rng=rng,
        stores_df=stores_df,
        orders_df=orders_df,
        order_items_df=order_items_df,
        inv_df=inv_df,
    )

    datasets = {
        "dark_stores.csv": raw_stores,
        "skus.csv": skus_df,
        "riders.csv": riders_df,
        "customers.csv": cust_raw,
        "weather_data.csv": weather_df,
        "orders.csv": raw_orders,
        "order_items.csv": raw_items,
        "inventory_snapshots.csv": raw_inv,
        "rider_logs.csv": rider_logs_df,
        "ab_experiment_assignments.csv": ab_assign_df,
        "ab_experiment_events.csv": ab_events_df,
    }

    row_counts: dict[str, int] = {}
    for filename, df in datasets.items():
        out_path = raw_dir / filename
        df.to_csv(out_path, index=False)
        df.head(100).to_csv(sample_dir / filename, index=False)
        row_counts[filename] = len(df)
        logger.info("Wrote %s (%d rows)", out_path, len(df))

    # Persist SCD Type 2 versioned dimension snapshots alongside raw/staging
    stores_scd_df.to_csv(raw_dir / "dark_stores_scd_history.csv", index=False)
    skus_scd_df.to_csv(raw_dir / "skus_scd_history.csv", index=False)

    logger.info("Synthetic data generation complete.")
    return row_counts


if __name__ == "__main__":
    counts = run_data_generation()
    for name, cnt in counts.items():
        print(f"{name}: {cnt:,} rows")
