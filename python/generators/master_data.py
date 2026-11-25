"""Generators for master dimension entities: dark stores, SKUs (with SCD2 history), riders, customers, and weather."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Tuple

import numpy as np
import pandas as pd

from python.config import get_city_mapping, get_simulation_config


def generate_dark_stores(rng: np.random.Generator) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Generate 25 dark stores across 4 Indian metros plus SCD Type 2 rent-tier history."""
    city_map = get_city_mapping()["canonical_cities"]
    sim_cfg = get_simulation_config()
    start_date = pd.Timestamp(sim_cfg["date_range"]["start_date"], tz="Asia/Kolkata")

    rent_tier_map = {
        "South Bengaluru": ("PREMIUM", 410000),
        "East Bengaluru": ("STANDARD", 310000),
        "North Bengaluru": ("STANDARD", 260000),
        "Western Suburbs": ("PREMIUM", 540000),
        "Central Mumbai": ("HIGH_STREET", 480000),
        "South Mumbai": ("PREMIUM", 590000),
        "South Delhi": ("PREMIUM", 470000),
        "Gurugram": ("HIGH_STREET", 380000),
        "Noida & East Delhi": ("STANDARD", 270000),
        "Central Chennai": ("HIGH_STREET", 310000),
        "South Chennai": ("STANDARD", 250000),
        "North & West Chennai": ("STANDARD", 220000),
    }

    # Assign operational profiles to create realistic root-cause patterns across the 25 stores
    operational_profiles = [
        "HEALTHY", "PICKING_BOTTLENECK", "HIGH_RIDER_COST", "HEALTHY", "HIGH_DISCOUNT_BURN",
        "STOCKOUT_LOSS", "HEALTHY", "TRANSIT_DELAY", "RIDER_SHORTAGE", "HEALTHY",
        "HIGH_REFUND_COST", "PICKING_BOTTLENECK", "HIGH_RIDER_COST", "HEALTHY", "HEALTHY",
        "HIGH_DISCOUNT_BURN", "STOCKOUT_LOSS", "TRANSIT_DELAY", "HEALTHY", "HEALTHY",
        "RIDER_SHORTAGE", "HEALTHY", "PICKING_BOTTLENECK", "HEALTHY", "HEALTHY",
    ]

    rows = []
    store_idx = 1
    for city, info in city_map.items():
        state = info["state"]
        for zone_info in info["zones"]:
            zone = zone_info["zone"]
            pincodes = zone_info["pincodes"]
            rent_tier, base_rent = rent_tier_map[zone]
            for s_idx, store_name in enumerate(zone_info["stores"]):
                profile = operational_profiles[(store_idx - 1) % len(operational_profiles)]
                pincode = pincodes[s_idx % len(pincodes)]
                rent = round(base_rent * rng.uniform(0.94, 1.08), -3)
                # Capacity and staffing tuned by profile
                capacity = int(rng.integers(55, 85))
                staffing = int(rng.integers(14, 24))
                if profile == "PICKING_BOTTLENECK":
                    staffing = int(rng.integers(8, 12))
                    capacity = int(rng.integers(45, 58))
                rows.append({
                    "store_id": f"STR-{store_idx:03d}",
                    "store_name": f"{store_name} ({city})",
                    "city": city,
                    "state": state,
                    "pincode": pincode,
                    "zone": zone,
                    "rent_tier": rent_tier,
                    "monthly_rent": float(rent),
                    "operating_capacity": capacity,
                    "staffing_level": staffing,
                    "operational_profile": profile,
                    "effective_from": start_date.isoformat(),
                    "effective_to": None,
                    "is_current": True,
                })
                store_idx += 1

    stores_df = pd.DataFrame(rows)

    # Create SCD Type 2 rent-tier revision history for 5 high-demand stores on 2026-08-01
    mid_date = pd.Timestamp("2026-08-01 00:00:00", tz="Asia/Kolkata")
    scd_rows = []
    upgrade_ids = {"STR-001", "STR-008", "STR-012", "STR-015", "STR-021"}
    for _, row in stores_df.iterrows():
        r = row.to_dict()
        if r["store_id"] in upgrade_ids:
            old_row = r.copy()
            old_row["effective_to"] = (mid_date - timedelta(seconds=1)).isoformat()
            old_row["is_current"] = False
            scd_rows.append(old_row)

            new_row = r.copy()
            new_row["rent_tier"] = "PREMIUM" if r["rent_tier"] != "PREMIUM" else "HIGH_STREET"
            new_row["monthly_rent"] = round(r["monthly_rent"] * 1.12, -3)
            new_row["staffing_level"] = r["staffing_level"] + 2
            new_row["effective_from"] = mid_date.isoformat()
            new_row["effective_to"] = None
            new_row["is_current"] = True
            scd_rows.append(new_row)
        else:
            scd_rows.append(r)

    stores_scd_df = pd.DataFrame(scd_rows)
    return stores_df, stores_scd_df


def generate_skus(rng: np.random.Generator, n_skus: int = 650) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Generate realistic Indian quick-commerce SKUs across 8 grocery categories + SCD2 price/cost changes."""
    sim_cfg = get_simulation_config()
    start_date = pd.Timestamp(sim_cfg["date_range"]["start_date"], tz="Asia/Kolkata")

    catalog_specs = [
        ("Dairy", ["Milk & Curd", "Paneer & Cheese", "Butter & Ghee"], (24, 145), (0.14, 0.22), ["Amul", "Nandini", "Mother Dairy", "Milky Mist"]),
        ("Fruits & Vegetables", ["Fresh Vegetables", "Seasonal Fruits", "Leafy Greens"], (18, 95), (0.22, 0.32), ["FarmFresh Direct", "Sahyadri Farms", "Local Mandi Co"]),
        ("Beverages", ["Soft Drinks & Juices", "Tea & Coffee", "Energy & Health Drinks"], (20, 160), (0.18, 0.28), ["Tata Consumer", "Coca-Cola India", "PepsiCo", "Paper Boat"]),
        ("Snacks", ["Chips & Namkeen", "Biscuits & Cookies", "Chocolates"], (15, 110), (0.20, 0.30), ["Haldiram's", "Britannia", "ITC Foods", "Mondelez"]),
        ("Personal Care", ["Bath & Body", "Oral & Hair Care", "Skincare"], (35, 195), (0.24, 0.34), ["HUL", "Marico", "Dabur", "Mamaearth"]),
        ("Household Essentials", ["Detergents & Cleaners", "Paper & Disposables", "Pooja & Utility"], (30, 185), (0.20, 0.30), ["Reckitt", "P&G India", "Godrej Consumer"]),
        ("Bakery", ["Breads & Pav", "Cakes & Muffins", "Artisanal Bakes"], (25, 115), (0.22, 0.32), ["Modern Foods", "Harvest Gold", "Theobroma Supply"]),
        ("Packaged Foods", ["Instant Noodles & Pasta", "Staples & Atta", "Breakfast Cereals"], (25, 175), (0.16, 0.25), ["Nestle India", "ITC Aashirvaad", "Kellogg's", "MTR"]),
    ]

    adjectives = ["Classic", "Fresh", "Gold", "Premium", "Family Pack", "Mini", "Rich", "Organic", "Daily", "Active"]
    units = ["200g", "500g", "1kg", "250ml", "500ml", "1L", "Pack of 4", "150g", "100g", "750ml"]

    rows = []
    for i in range(1, n_skus + 1):
        cat, subcats, price_range, margin_range, suppliers = catalog_specs[(i - 1) % len(catalog_specs)]
        subcat = subcats[i % len(subcats)]
        supplier = suppliers[i % len(suppliers)]
        adj = adjectives[(i * 3) % len(adjectives)]
        unit = units[(i * 7) % len(units)]
        selling_price = round(float(rng.uniform(*price_range)), 2)
        margin_pct = float(rng.uniform(*margin_range))
        unit_cost = round(selling_price * (1.0 - margin_pct), 2)
        gross_margin = round(selling_price - unit_cost, 2)
        reorder_threshold = int(rng.integers(12, 35))
        is_peak_hero = (i <= 90)  # Top 90 high-velocity evening SKUs

        rows.append({
            "sku_id": f"SKU-{i:04d}",
            "sku_name": f"{supplier.split()[0]} {adj} {subcat.split('&')[0].strip()} {unit}",
            "category": cat,
            "subcategory": subcat,
            "unit_cost": unit_cost,
            "selling_price": selling_price,
            "gross_margin": gross_margin,
            "gross_margin_pct": round(margin_pct * 100.0, 2),
            "supplier": supplier,
            "reorder_threshold": reorder_threshold,
            "is_peak_hero": is_peak_hero,
            "effective_from": start_date.isoformat(),
            "effective_to": None,
            "is_current": True,
        })

    skus_df = pd.DataFrame(rows)

    # SCD Type 2 price/cost changes on 2026-08-01 for ~10% of SKUs
    mid_date = pd.Timestamp("2026-08-01 00:00:00", tz="Asia/Kolkata")
    changed_indices = set(rng.choice(len(skus_df), size=max(1, int(n_skus * 0.10)), replace=False))
    scd_rows = []
    for idx, row in skus_df.iterrows():
        r = row.to_dict()
        if idx in changed_indices:
            old_row = r.copy()
            old_row["effective_to"] = (mid_date - timedelta(seconds=1)).isoformat()
            old_row["is_current"] = False
            scd_rows.append(old_row)

            new_row = r.copy()
            cost_bump = float(rng.uniform(1.04, 1.12))
            price_bump = float(rng.uniform(1.02, 1.07))
            new_row["unit_cost"] = round(r["unit_cost"] * cost_bump, 2)
            new_row["selling_price"] = round(r["selling_price"] * price_bump, 2)
            new_row["gross_margin"] = round(new_row["selling_price"] - new_row["unit_cost"], 2)
            new_row["gross_margin_pct"] = round((new_row["gross_margin"] / new_row["selling_price"]) * 100.0, 2)
            new_row["effective_from"] = mid_date.isoformat()
            new_row["effective_to"] = None
            new_row["is_current"] = True
            scd_rows.append(new_row)
        else:
            scd_rows.append(r)

    skus_scd_df = pd.DataFrame(scd_rows)
    return skus_df, skus_scd_df


def generate_riders(rng: np.random.Generator, stores_df: pd.DataFrame, n_riders: int = 600) -> pd.DataFrame:
    """Generate 600 riders assigned across the 25 dark stores."""
    store_ids = stores_df["store_id"].tolist()
    profiles = dict(zip(stores_df["store_id"], stores_df["operational_profile"]))

    vehicle_types = ["EV_SCOOTER", "PETROL_BIKE", "BICYCLE"]
    vehicle_probs = [0.42, 0.48, 0.10]
    emp_types = ["FULL_TIME", "GIG_PART_TIME"]
    emp_probs = [0.55, 0.45]
    payout_tiers = ["BASE", "TIER_1", "TIER_2"]
    statuses = ["ACTIVE", "ON_LEAVE", "OFFLINE"]
    status_probs = [0.84, 0.08, 0.08]

    # Distribute slightly fewer active riders to RIDER_SHORTAGE stores
    weights = np.array([
        0.70 if profiles[s] == "RIDER_SHORTAGE" else (1.15 if profiles[s] == "HEALTHY" else 1.0)
        for s in store_ids
    ])
    weights = weights / weights.sum()

    assigned_stores = rng.choice(store_ids, size=n_riders, p=weights)
    vehicles = rng.choice(vehicle_types, size=n_riders, p=vehicle_probs)
    emps = rng.choice(emp_types, size=n_riders, p=emp_probs)
    tiers = rng.choice(payout_tiers, size=n_riders, p=[0.45, 0.35, 0.20])
    avail = rng.choice(statuses, size=n_riders, p=status_probs)

    rows = []
    for i in range(n_riders):
        rows.append({
            "rider_id": f"RDR-{i + 1:04d}",
            "vehicle_type": str(vehicles[i]),
            "employment_type": str(emps[i]),
            "payout_tier": str(tiers[i]),
            "assigned_store": str(assigned_stores[i]),
            "availability_status": str(avail[i]),
        })
    return pd.DataFrame(rows)


def generate_customers(
    rng: np.random.Generator,
    stores_df: pd.DataFrame,
    n_customers: int = 42000,
) -> pd.DataFrame:
    """Generate 42,000 customers across the 4 cities with deterministic home store affinity."""
    sim_cfg = get_simulation_config()
    start_ts = pd.Timestamp(sim_cfg["date_range"]["start_date"], tz="Asia/Kolkata")

    city_counts = stores_df["city"].value_counts(normalize=True)
    cities = city_counts.index.tolist()
    city_probs = city_counts.values

    channels = ["ORGANIC", "PERFORMANCE_ADS", "REFERRAL", "APP_STORE", "PARTNERSHIP"]
    channel_probs = [0.30, 0.34, 0.16, 0.12, 0.08]
    segments = ["CONVENIENCE_FIRST", "VALUE_SEEKER", "FAMILY_BULK", "OCCASIONAL"]
    segment_probs = [0.32, 0.30, 0.20, 0.18]

    cust_cities = rng.choice(cities, size=n_customers, p=city_probs)
    cust_channels = rng.choice(channels, size=n_customers, p=channel_probs)
    cust_segments = rng.choice(segments, size=n_customers, p=segment_probs)

    # Registration dates span from 90 days before window start up to day 175
    reg_offsets_days = rng.integers(-90, 175, size=n_customers)
    reg_dates = [(start_ts + timedelta(days=int(d))).date().isoformat() for d in reg_offsets_days]

    # Map each customer to a primary city store
    city_to_stores = stores_df.groupby("city")["store_id"].apply(list).to_dict()
    home_stores = [
        city_to_stores[c][int(rng.integers(0, len(city_to_stores[c])))]
        for c in cust_cities
    ]

    rows = []
    for i in range(n_customers):
        rows.append({
            "customer_id": f"CUST-{i + 1:06d}",
            "acquisition_channel": str(cust_channels[i]),
            "customer_segment": str(cust_segments[i]),
            "city": str(cust_cities[i]),
            "home_store_id": home_stores[i],
            "registration_date": reg_dates[i],
            "first_order_date": None,
        })
    return pd.DataFrame(rows)


def generate_weather_data(rng: np.random.Generator) -> pd.DataFrame:
    """Generate 30-minute weather telemetry across all 4 cities over the 6-month period."""
    sim_cfg = get_simulation_config()
    start_ist = pd.Timestamp(sim_cfg["date_range"]["start_date"], tz="Asia/Kolkata")
    n_days = int(sim_cfg["date_range"]["days"])
    total_slots = n_days * 48  # 30-minute slots

    cities = ["Bengaluru", "Mumbai", "Delhi NCR", "Chennai"]
    # Monthly heavy-rain / monsoon probability per city (May-Oct Indian seasonal pattern)
    month_rain_prob = {
        "Mumbai": {5: 0.04, 6: 0.35, 7: 0.55, 8: 0.50, 9: 0.32, 10: 0.10},
        "Bengaluru": {5: 0.14, 6: 0.22, 7: 0.28, 8: 0.30, 9: 0.28, 10: 0.24},
        "Delhi NCR": {5: 0.03, 6: 0.12, 7: 0.30, 8: 0.32, 9: 0.18, 10: 0.04},
        "Chennai": {5: 0.05, 6: 0.10, 7: 0.14, 8: 0.18, 9: 0.22, 10: 0.40},
    }

    slot_times_ist = [start_ist + timedelta(minutes=30 * s) for s in range(total_slots)]
    rows = []
    wid = 1

    for city in cities:
        # Use Markov-like persistence so rain events last 1.5–4 hours realistically
        state = "NORMAL"
        for ts_ist in slot_times_ist:
            p_wet = month_rain_prob[city][ts_ist.month]
            u = rng.random()
            if state == "NORMAL":
                if u < p_wet * 0.45:
                    state = "HEAVY_RAIN" if rng.random() < 0.38 else "MONSOON"
            elif state == "MONSOON":
                if u < 0.28:
                    state = "NORMAL"
                elif u < 0.48:
                    state = "HEAVY_RAIN"
            else:  # HEAVY_RAIN
                if u < 0.35:
                    state = "MONSOON"
                elif u < 0.50:
                    state = "NORMAL"

            if state == "NORMAL":
                rain_mm = 0.0
                temp_c = round(float(rng.uniform(25.0, 37.0)), 1)
            elif state == "MONSOON":
                rain_mm = round(float(rng.uniform(2.0, 12.0)), 1)
                temp_c = round(float(rng.uniform(22.0, 29.0)), 1)
            else:
                rain_mm = round(float(rng.uniform(15.0, 48.0)), 1)
                temp_c = round(float(rng.uniform(21.0, 26.5)), 1)

            ts_utc = ts_ist.tz_convert("UTC")
            rows.append({
                "weather_id": f"WTH-{wid:06d}",
                "city": city,
                "timestamp_utc": ts_utc.isoformat(),
                "timestamp_ist": ts_ist.isoformat(),
                "weather_tag": state,
                "rainfall_mm_hr": rain_mm,
                "temperature_c": temp_c,
            })
            wid += 1

    return pd.DataFrame(rows)


def deterministic_ab_group(customer_id: str, experiment_name: str = "free_delivery_threshold_199_vs_249") -> str:
    """Assign customer deterministically (50/50) using SHA-256 hash."""
    digest = hashlib.sha256(f"{experiment_name}:{customer_id}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 2
    return "CONTROL" if bucket == 0 else "TREATMENT"
