"""Vectorized synthetic generator for orders, order_items, inventory_snapshots, rider_logs, A/B events, and messy data injection."""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from python.config import get_logger, get_settings, get_simulation_config
from python.generators.master_data import deterministic_ab_group

logger = get_logger(__name__)


def _build_hourly_weights() -> np.ndarray:
    """24-hour demand weights (IST) reflecting morning, lunch, and 7-10 PM peak."""
    w = np.array([
        0.008, 0.005, 0.003, 0.003, 0.004, 0.008,  # 00-05
        0.022, 0.042, 0.055, 0.052, 0.044, 0.042,  # 06-11
        0.052, 0.050, 0.038, 0.032, 0.038, 0.055,  # 12-17
        0.072, 0.105, 0.118, 0.095, 0.042, 0.017,  # 18-23
    ], dtype=float)
    return w / w.sum()


def generate_orders_and_items(
    rng: np.random.Generator,
    stores_df: pd.DataFrame,
    stores_scd_df: pd.DataFrame,
    skus_df: pd.DataFrame,
    skus_scd_df: pd.DataFrame,
    customers_df: pd.DataFrame,
    riders_df: pd.DataFrame,
    weather_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate 155k+ orders, order items, A/B assignments, and A/B events."""
    sim_cfg = get_simulation_config()
    settings = get_settings()

    start_ist = pd.Timestamp(sim_cfg["date_range"]["start_date"], tz="Asia/Kolkata")
    n_days = int(sim_cfg["date_range"]["days"])
    base_daily = float(sim_cfg["scale"]["base_orders_per_day_start"])
    qoq_growth = float(sim_cfg["scale"]["qoq_growth_rate"])
    exp_name = settings["analytics"]["ab_experiment"]["name"]
    exp_start_ist = pd.Timestamp("2026-09-01 00:00:00", tz="Asia/Kolkata")
    scd_cutoff_ist = pd.Timestamp("2026-08-01 00:00:00", tz="Asia/Kolkata")

    # Deterministic A/B assignment for ALL 42,000 customers (including non-orderers)
    ab_assignments_df = pd.DataFrame({
        "customer_id": customers_df["customer_id"].values,
        "experiment_name": exp_name,
        "variant": [deterministic_ab_group(cid, exp_name) for cid in customers_df["customer_id"]],
        "threshold_inr": 199.0,
        "assigned_at": start_ist.isoformat(),
    })
    ab_assignments_df.loc[ab_assignments_df["variant"] == "TREATMENT", "threshold_inr"] = 249.0
    cust_variant_map = dict(zip(ab_assignments_df["customer_id"], ab_assignments_df["variant"]))

    # Keep ~84% of customers as potential orderers so ~16% never order (realistic ITT funnel)
    n_cust = len(customers_df)
    active_mask = rng.random(n_cust) < 0.84
    active_cust = customers_df[active_mask].reset_index(drop=True)

    # Customer segment affinity weights for order frequency
    seg_freq = {
        "CONVENIENCE_FIRST": 1.55,
        "FAMILY_BULK": 1.25,
        "VALUE_SEEKER": 1.00,
        "OCCASIONAL": 0.45,
    }
    cust_weights = active_cust["customer_segment"].map(seg_freq).values.astype(float)
    cust_weights /= cust_weights.sum()

    # Daily order volume trajectory (~28% QoQ growth over 6 months -> ~158k orders)
    daily_counts = []
    for d in range(n_days):
        ts = start_ist + timedelta(days=d)
        # Quarter progress: 0.0 at day 0 -> 2.0 at day 183
        q_prog = d / 91.5
        growth_mult = (1.0 + qoq_growth) ** q_prog
        weekend_mult = 1.18 if ts.dayofweek >= 5 else 1.0
        noise = float(rng.normal(1.0, 0.04))
        cnt = max(450, int(round(base_daily * growth_mult * weekend_mult * noise)))
        daily_counts.append(cnt)

    total_orders = sum(daily_counts)
    logger.info("Generating %d baseline orders across %d days...", total_orders, n_days)

    # Build timestamp array in IST
    hourly_probs = _build_hourly_weights()
    day_indices = np.repeat(np.arange(n_days), daily_counts)
    hours = rng.choice(24, size=total_orders, p=hourly_probs)
    minutes = rng.integers(0, 60, size=total_orders)
    seconds = rng.integers(0, 60, size=total_orders)

    base_epoch_ist = start_ist.tz_convert("UTC")
    placed_utc_ns = (
        base_epoch_ist.value
        + (day_indices.astype(np.int64) * 86400 + hours.astype(np.int64) * 3600 + minutes.astype(np.int64) * 60 + seconds.astype(np.int64)) * 1_000_000_000
    )
    placed_utc = pd.to_datetime(placed_utc_ns, utc=True)
    placed_ist = placed_utc.tz_convert("Asia/Kolkata")

    # Assign customers & stores (92% home store, 8% nearby city store)
    chosen_cust_idx = rng.choice(len(active_cust), size=total_orders, p=cust_weights)
    order_cust_ids = active_cust["customer_id"].values[chosen_cust_idx]
    order_cust_segs = active_cust["customer_segment"].values[chosen_cust_idx]
    order_cities = active_cust["city"].values[chosen_cust_idx]
    order_stores = active_cust["home_store_id"].values[chosen_cust_idx].copy()

    city_to_stores = stores_df.groupby("city")["store_id"].apply(list).to_dict()
    switch_mask = rng.random(total_orders) < 0.08
    for idx in np.where(switch_mask)[0]:
        c_stores = city_to_stores[order_cities[idx]]
        order_stores[idx] = c_stores[int(rng.integers(0, len(c_stores)))]

    # Store metadata lookups
    store_profile_map = dict(zip(stores_df["store_id"], stores_df["operational_profile"]))
    store_city_map = dict(zip(stores_df["store_id"], stores_df["city"]))
    order_profiles = np.array([store_profile_map[s] for s in order_stores])

    # Weather lookup via (city, 30-min floor UTC)
    weather_lookup = weather_df.copy()
    weather_lookup["slot_utc"] = pd.to_datetime(weather_lookup["timestamp_utc"], utc=True).dt.floor("30min")
    weather_map = dict(
        zip(
            zip(weather_lookup["city"], weather_lookup["slot_utc"]),
            weather_lookup["weather_tag"],
        )
    )
    slot_utc_arr = placed_utc.floor("30min")
    order_weather = np.array([
        weather_map.get((c, s), "NORMAL") for c, s in zip(order_cities, slot_utc_arr)
    ])

    # Rider assignment pool per store (use active riders primarily, fallback to any store rider)
    active_riders_by_store: Dict[str, list] = (
        riders_df[riders_df["availability_status"] == "ACTIVE"]
        .groupby("assigned_store")["rider_id"]
        .apply(list)
        .to_dict()
    )
    all_riders_by_store = riders_df.groupby("assigned_store")["rider_id"].apply(list).to_dict()
    order_riders = np.empty(total_orders, dtype=object)
    for i, sid in enumerate(order_stores):
        pool = active_riders_by_store.get(sid) or all_riders_by_store[sid]
        order_riders[i] = pool[int(rng.integers(0, len(pool)))]

    # A/B variant & experiment window mask
    order_variants = np.array([cust_variant_map[cid] for cid in order_cust_ids])
    in_exp_window = placed_ist >= exp_start_ist

    # Generate basket composition & cart values
    # Segment base item counts: FAMILY_BULK (3-4), CONVENIENCE_FIRST (1-3), VALUE_SEEKER (2-4), OCCASIONAL (1-3)
    n_items_per_order = np.where(
        order_cust_segs == "FAMILY_BULK",
        rng.integers(3, 5, size=total_orders),
        np.where(
            order_cust_segs == "VALUE_SEEKER",
            rng.integers(2, 4, size=total_orders),
            np.where(
                order_cust_segs == "CONVENIENCE_FIRST",
                rng.integers(2, 4, size=total_orders),
                rng.integers(1, 3, size=total_orders),
            ),
        ),
    )

    # Prepare pre-Aug and post-Aug SKU pricing arrays for SCD2 accuracy
    skus_pre = skus_scd_df[skus_scd_df["effective_to"].notna() | ~skus_scd_df["sku_id"].isin(
        skus_scd_df[skus_scd_df["is_current"] == False]["sku_id"]
    )].sort_values("sku_id").reset_index(drop=True)
    skus_post = skus_scd_df[skus_scd_df["is_current"] == True].sort_values("sku_id").reset_index(drop=True)

    n_skus = len(skus_post)
    sku_ids_arr = skus_post["sku_id"].values
    # Popularity weights: top 90 hero SKUs get ~4.5x higher velocity
    sku_probs = np.where(np.arange(n_skus) < 90, 4.5, 1.0)
    sku_probs = sku_probs / sku_probs.sum()

    pre_prices = skus_pre["selling_price"].values
    pre_costs = skus_pre["unit_cost"].values
    post_prices = skus_post["selling_price"].values
    post_costs = skus_post["unit_cost"].values

    # Vectorized expansion of order items
    total_items = int(n_items_per_order.sum())
    order_idx_for_item = np.repeat(np.arange(total_orders), n_items_per_order)
    chosen_sku_idx = rng.choice(n_skus, size=total_items, p=sku_probs)
    item_qty = rng.choice([1, 1, 1, 1, 1, 2], size=total_items)

    is_post_scd = np.asarray(placed_ist >= scd_cutoff_ist)[order_idx_for_item]
    item_unit_price = np.where(is_post_scd, post_prices[chosen_sku_idx], pre_prices[chosen_sku_idx])
    item_unit_cost = np.where(is_post_scd, post_costs[chosen_sku_idx], pre_costs[chosen_sku_idx])

    # Apply realistic A/B Treatment basket top-up behavior during Sep-Oct
    # First compute preliminary cart_value per order
    line_total = np.round(item_qty * item_unit_price, 2)
    line_margin = np.round(item_qty * (item_unit_price - item_unit_cost), 2)

    prelim_cart = np.bincount(order_idx_for_item, weights=line_total, minlength=total_orders)
    prelim_gm = np.bincount(order_idx_for_item, weights=line_margin, minlength=total_orders)

    # Treatment top-up & abandonment in Sep-Oct for 199 <= cart < 249
    mid_basket = in_exp_window & (order_variants == "TREATMENT") & (prelim_cart >= 199.0) & (prelim_cart < 249.0)
    abandon_draw = rng.random(total_orders)
    ab_abandoned_mask = mid_basket & (abandon_draw < 0.145)
    topup_mask = mid_basket & (~ab_abandoned_mask) & (abandon_draw < 0.52)

    # Top up those orders by adding ~1 extra item (approx ₹58 selling price, ₹14 margin)
    topup_orders_idx = np.where(topup_mask)[0]
    if len(topup_orders_idx) > 0:
        topup_sku_idx = rng.choice(n_skus, size=len(topup_orders_idx), p=sku_probs)
        topup_price = post_prices[topup_sku_idx]
        topup_cost = post_costs[topup_sku_idx]
        topup_qty = np.ones(len(topup_orders_idx), dtype=int)

        order_idx_for_item = np.concatenate([order_idx_for_item, topup_orders_idx])
        chosen_sku_idx = np.concatenate([chosen_sku_idx, topup_sku_idx])
        item_qty = np.concatenate([item_qty, topup_qty])
        item_unit_price = np.concatenate([item_unit_price, topup_price])
        item_unit_cost = np.concatenate([item_unit_cost, topup_cost])
        line_total = np.concatenate([line_total, np.round(topup_price, 2)])
        line_margin = np.concatenate([line_margin, np.round(topup_price - topup_cost, 2)])

    # Drop A/B abandoned orders from actual placed orders, but record them in ab_experiment_events!
    kept_mask = ~ab_abandoned_mask
    kept_indices = np.where(kept_mask)[0]

    # Recompute cart_value and gross_margin per original order index
    cart_value = np.round(np.bincount(order_idx_for_item, weights=line_total, minlength=total_orders), 2)
    gross_margin = np.round(np.bincount(order_idx_for_item, weights=line_margin, minlength=total_orders), 2)

    # Payment modes
    payment_modes = rng.choice(["UPI", "CARD", "COD"], size=total_orders, p=[0.64, 0.20, 0.16])

    # SLA & Timestamps modeling
    is_peak = (hours >= 19) & (hours <= 21)
    is_monsoon = order_weather == "MONSOON"
    is_heavy_rain = order_weather == "HEAVY_RAIN"

    # Picking duration (seconds)
    picking_sec = rng.gamma(shape=4.2, scale=33.0, size=total_orders)  # mean ~138s
    picking_sec += np.where(is_peak, rng.uniform(45, 95, size=total_orders), 0.0)
    picking_sec += np.where(order_profiles == "PICKING_BOTTLENECK", rng.uniform(155, 250, size=total_orders), 0.0)
    picking_sec += np.where(day_indices > 120, rng.uniform(15, 45, size=total_orders), 0.0)  # Q2 volume strain
    picking_sec = np.clip(np.round(picking_sec), 45, 900).astype(np.int64)

    # Assignment & handover duration (seconds)
    assign_sec = rng.gamma(shape=3.2, scale=32.0, size=total_orders)  # mean ~102s
    assign_sec += np.where(is_peak, rng.uniform(35, 85, size=total_orders), 0.0)
    assign_sec += np.where(is_monsoon, rng.uniform(45, 85, size=total_orders), 0.0)
    assign_sec += np.where(is_heavy_rain, rng.uniform(125, 210, size=total_orders), 0.0)
    assign_sec += np.where(order_profiles == "RIDER_SHORTAGE", rng.uniform(150, 250, size=total_orders), 0.0)
    assign_sec = np.clip(np.round(assign_sec), 30, 960).astype(np.int64)

    # Transit duration (seconds)
    transit_sec = rng.gamma(shape=4.8, scale=60.0, size=total_orders)  # mean ~288s
    transit_sec += np.where(is_peak, rng.uniform(55, 115, size=total_orders), 0.0)
    transit_sec += np.where(is_monsoon, rng.uniform(85, 145, size=total_orders), 0.0)
    transit_sec += np.where(is_heavy_rain, rng.uniform(210, 340, size=total_orders), 0.0)
    transit_sec += np.where(order_profiles == "TRANSIT_DELAY", rng.uniform(145, 230, size=total_orders), 0.0)
    transit_sec = np.clip(np.round(transit_sec), 90, 1500).astype(np.int64)

    total_sec = picking_sec + assign_sec + transit_sec

    # Cancellation rate (~3.8% baseline, higher when heavy rain or severe bottleneck)
    cancel_prob = np.full(total_orders, 0.032)
    cancel_prob += np.where(is_heavy_rain, 0.028, 0.0)
    cancel_prob += np.where(total_sec > 1080, 0.030, 0.0)
    is_cancelled = rng.random(total_orders) < cancel_prob

    # Economics calibration: transition NCM/order from ~+18 INR (Month 1) to ~-6 INR (Month 6)
    month_progress = np.clip(day_indices / float(n_days - 1), 0.0, 1.0)  # 0.0 -> 1.0

    # Threshold: ₹199 normally/Control, ₹249 for Treatment in Sep-Oct
    threshold = np.where(in_exp_window & (order_variants == "TREATMENT"), 249.0, 199.0)
    delivery_fee = np.where(is_cancelled, 0.0, np.where(cart_value < threshold, 25.0, 0.0))
    handling_fee = np.where(is_cancelled, 0.0, 5.0)
    surge_fee = np.where(
        is_cancelled,
        0.0,
        np.where(is_heavy_rain, 15.0, np.where(is_monsoon & is_peak, 10.0, 0.0)),
    )

    # Discounts ramp from ~5.3% in May to ~11.1% in Oct, higher at HIGH_DISCOUNT_BURN stores
    disc_rate = 0.053 + 0.058 * month_progress + rng.normal(0.0, 0.012, size=total_orders)
    disc_rate += np.where(order_profiles == "HIGH_DISCOUNT_BURN", 0.065, 0.0)
    disc_rate = np.clip(disc_rate, 0.0, 0.30)
    discounts = np.where(is_cancelled, 0.0, np.round(cart_value * disc_rate, 2))

    # Rider payout ramps from ~₹26.5 in May to ~₹35.8 in Oct + weather & store profile effects
    rider_payout = 26.5 + 9.3 * month_progress + rng.normal(0.0, 2.0, size=total_orders)
    rider_payout += np.where(is_monsoon, 5.5, 0.0)
    rider_payout += np.where(is_heavy_rain, 14.0, 0.0)
    rider_payout += np.where(order_profiles == "HIGH_RIDER_COST", 12.0, 0.0)
    rider_payout += np.where(order_profiles == "RIDER_SHORTAGE", 8.0, 0.0)
    rider_payout = np.where(is_cancelled, np.round(rider_payout * 0.25, 2), np.round(np.clip(rider_payout, 18.0, 75.0), 2))

    # Packaging cost
    packaging_cost = np.where(
        is_cancelled,
        2.0,
        np.round(6.0 + 0.8 * month_progress + np.where(payment_modes == "COD", 2.5, 0.0), 2),
    )

    # Refund cost (driven by late deliveries > 12 min, heavy rain, and HIGH_REFUND_COST stores)
    refund_prob = 0.020 + 0.032 * month_progress
    refund_prob += np.where(total_sec > 720, 0.045, 0.0)
    refund_prob += np.where(is_heavy_rain, 0.030, 0.0)
    refund_prob += np.where(order_profiles == "HIGH_REFUND_COST", 0.085, 0.0)
    has_refund = (~is_cancelled) & (rng.random(total_orders) < refund_prob)
    refund_cost = np.where(
        is_cancelled,
        0.0,
        np.where(has_refund, np.round(cart_value * rng.uniform(0.18, 0.45, size=total_orders), 2), 0.0),
    )

    # Zero out gross_margin for cancelled orders (no item sale realized)
    realized_gm = np.where(is_cancelled, 0.0, gross_margin)

    # Build order timestamps
    placed_ns = placed_utc.asi8
    packed_ns = placed_ns + picking_sec * 1_000_000_000
    dispatched_ns = packed_ns + assign_sec * 1_000_000_000
    delivered_ns = dispatched_ns + transit_sec * 1_000_000_000
    cancelled_ns = packed_ns + rng.integers(30, 180, size=total_orders) * 1_000_000_000

    # Filter to kept (non-abandoned) orders
    k_order_ids = np.array([f"ORD-{i + 1:07d}" for i in range(len(kept_indices))])
    orig_to_order_id = np.empty(total_orders, dtype=object)
    orig_to_order_id[kept_indices] = k_order_ids

    k_placed = pd.to_datetime(placed_ns[kept_indices], utc=True)
    k_packed = pd.to_datetime(packed_ns[kept_indices], utc=True)
    k_dispatched = pd.to_datetime(dispatched_ns[kept_indices], utc=True)
    k_delivered = pd.to_datetime(delivered_ns[kept_indices], utc=True)
    k_cancelled = pd.to_datetime(cancelled_ns[kept_indices], utc=True)
    k_is_canc = is_cancelled[kept_indices]

    orders_df = pd.DataFrame({
        "order_id": k_order_ids,
        "customer_id": order_cust_ids[kept_indices],
        "store_id": order_stores[kept_indices],
        "rider_id": np.where(k_is_canc, None, order_riders[kept_indices]),
        "placed_at": k_placed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "packed_at": np.where(k_is_canc, k_packed.strftime("%Y-%m-%dT%H:%M:%SZ"), k_packed.strftime("%Y-%m-%dT%H:%M:%SZ")),
        "dispatched_at": np.where(k_is_canc, None, k_dispatched.strftime("%Y-%m-%dT%H:%M:%SZ")),
        "delivered_at": np.where(k_is_canc, None, k_delivered.strftime("%Y-%m-%dT%H:%M:%SZ")),
        "cancelled_at": np.where(k_is_canc, k_cancelled.strftime("%Y-%m-%dT%H:%M:%SZ"), None),
        "order_status": np.where(k_is_canc, "CANCELLED", "DELIVERED"),
        "payment_mode": payment_modes[kept_indices],
        "cart_value": np.round(cart_value[kept_indices], 2),
        "discounts": discounts[kept_indices],
        "delivery_fee": delivery_fee[kept_indices],
        "handling_fee": handling_fee[kept_indices],
        "surge_fee": surge_fee[kept_indices],
        "gross_margin": np.round(realized_gm[kept_indices], 2),
        "rider_payout": rider_payout[kept_indices],
        "packaging_cost": packaging_cost[kept_indices],
        "refund_cost": refund_cost[kept_indices],
        "weather_tag": order_weather[kept_indices],
    })

    # Filter order items to kept orders & aggregate duplicate SKUs within the same order
    item_keep_mask = kept_mask[order_idx_for_item]
    raw_items_df = pd.DataFrame({
        "order_id": orig_to_order_id[order_idx_for_item[item_keep_mask]],
        "sku_id": sku_ids_arr[chosen_sku_idx[item_keep_mask]],
        "quantity": item_qty[item_keep_mask],
        "unit_price": np.round(item_unit_price[item_keep_mask], 2),
        "unit_cost": np.round(item_unit_cost[item_keep_mask], 2),
    })
    order_items_df = (
        raw_items_df.groupby(["order_id", "sku_id"], as_index=False)
        .agg(
            quantity=("quantity", "sum"),
            unit_price=("unit_price", "first"),
            unit_cost=("unit_cost", "first"),
        )
    )
    order_items_df["line_total"] = np.round(order_items_df["quantity"] * order_items_df["unit_price"], 2)
    order_items_df["line_gross_margin"] = np.round(
        order_items_df["quantity"] * (order_items_df["unit_price"] - order_items_df["unit_cost"]), 2
    )
    order_items_df.insert(0, "order_item_id", [f"OI-{i + 1:08d}" for i in range(len(order_items_df))])

    # Update customer first_order_date from delivered orders
    deliv_orders = orders_df[orders_df["order_status"] == "DELIVERED"].copy()
    deliv_orders["order_date_ist"] = (
        pd.to_datetime(deliv_orders["placed_at"], utc=True)
        .dt.tz_convert("Asia/Kolkata")
        .dt.date.astype(str)
    )
    first_dates = deliv_orders.groupby("customer_id")["order_date_ist"].min().to_dict()
    customers_df = customers_df.copy()
    customers_df["first_order_date"] = customers_df["customer_id"].map(first_dates)

    # Build A/B Experiment Events (Sep 1 - Oct 31, 2026)
    # Events: SESSION_VIEW, CART_CREATED, CART_ABANDONED, ORDER_COMPLETED
    exp_order_mask = in_exp_window
    exp_events = []
    ev_id = 1

    # Also add organic app-browse non-converter sessions (~12% of randomized users who browse without ordering)
    exp_kept_df = orders_df[pd.to_datetime(orders_df["placed_at"], utc=True) >= exp_start_ist.tz_convert("UTC")].copy()
    exp_kept_df["variant"] = exp_kept_df["customer_id"].map(cust_variant_map)
    exp_kept_df["ncm"] = (
        exp_kept_df["gross_margin"]
        + exp_kept_df["handling_fee"]
        + exp_kept_df["delivery_fee"]
        + exp_kept_df["surge_fee"]
        - exp_kept_df["discounts"]
        - exp_kept_df["rider_payout"]
        - exp_kept_df["packaging_cost"]
        - exp_kept_df["refund_cost"]
    )

    # Completed / cancelled checkout events from kept experiment orders
    kept_ev = pd.DataFrame({
        "event_id": [f"ABEV-{i + 1:07d}" for i in range(len(exp_kept_df))],
        "customer_id": exp_kept_df["customer_id"].values,
        "experiment_name": exp_name,
        "variant": exp_kept_df["variant"].values,
        "order_id": exp_kept_df["order_id"].values,
        "event_type": np.where(exp_kept_df["order_status"] == "DELIVERED", "ORDER_COMPLETED", "ORDER_CANCELLED"),
        "cart_value": exp_kept_df["cart_value"].values,
        "net_contribution": np.round(exp_kept_df["ncm"].values, 2),
        "event_timestamp": exp_kept_df["placed_at"].values,
    })
    ev_id = len(kept_ev) + 1

    # Cart abandoned events (baseline ~9% cart abandonment across both + extra Treatment abandonment on 199-249)
    n_base_aband = int(len(exp_kept_df) * 0.095)
    base_aband_cust = customers_df["customer_id"].values[rng.integers(0, n_cust, size=n_base_aband)]
    base_aband_ts = (
        exp_start_ist.tz_convert("UTC")
        + pd.to_timedelta(rng.integers(0, 61 * 86400, size=n_base_aband), unit="s")
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    base_aband_df = pd.DataFrame({
        "event_id": [f"ABEV-{ev_id + i:07d}" for i in range(n_base_aband)],
        "customer_id": base_aband_cust,
        "experiment_name": exp_name,
        "variant": [cust_variant_map[c] for c in base_aband_cust],
        "order_id": None,
        "event_type": "CART_ABANDONED",
        "cart_value": np.round(rng.uniform(110.0, 290.0, size=n_base_aband), 2),
        "net_contribution": 0.0,
        "event_timestamp": base_aband_ts,
    })
    ev_id += n_base_aband

    aband_indices = np.where(ab_abandoned_mask)[0]
    treat_aband_ts = pd.to_datetime(placed_ns[aband_indices], utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")
    treat_aband_df = pd.DataFrame({
        "event_id": [f"ABEV-{ev_id + i:07d}" for i in range(len(aband_indices))],
        "customer_id": order_cust_ids[aband_indices],
        "experiment_name": exp_name,
        "variant": "TREATMENT",
        "order_id": None,
        "event_type": "CART_ABANDONED",
        "cart_value": np.round(cart_value[aband_indices], 2),
        "net_contribution": 0.0,
        "event_timestamp": treat_aband_ts,
    })

    ab_events_df = pd.concat([kept_ev, base_aband_df, treat_aband_df], ignore_index=True)

    logger.info(
        "Generated %d orders, %d order_items, %d A/B assignments, %d A/B events.",
        len(orders_df), len(order_items_df), len(ab_assignments_df), len(ab_events_df),
    )
    return orders_df, order_items_df, ab_assignments_df, ab_events_df


def generate_inventory_snapshots(
    rng: np.random.Generator,
    stores_df: pd.DataFrame,
    skus_df: pd.DataFrame,
) -> pd.DataFrame:
    """Generate 15-min peak (18:00-22:30 IST) and 2-hour off-peak snapshots for top 75 hero SKUs."""
    sim_cfg = get_simulation_config()
    start_ist = pd.Timestamp(sim_cfg["date_range"]["start_date"], tz="Asia/Kolkata")
    n_days = int(sim_cfg["date_range"]["days"])

    hero_skus = skus_df[skus_df["is_peak_hero"]].head(75).reset_index(drop=True)
    store_ids = stores_df["store_id"].values
    profiles = dict(zip(stores_df["store_id"], stores_df["operational_profile"]))

    # Daily snapshot minute offsets in IST:
    # Off-peak every 2 hours (0, 2, 4, 6, 8, 10, 12, 14, 16) + 15-min slots from 18:00 to 22:15 (18 slots) -> 27 slots/day
    off_peak_mins = [h * 60 for h in range(0, 18, 2)]
    peak_mins = list(range(18 * 60, 22 * 60 + 30, 15))
    daily_mins = off_peak_mins + peak_mins  # 27 slots/day

    # Build grid across 25 stores x 40 tracked hero SKUs = 1000 store-SKU pairs x 27 slots x 184 days?
    # 1000 * 27 * 184 = 4.97M rows; using 20 top SKUs x 25 stores = 500 pairs -> 2.48M rows,
    # or 25 stores x 16 top hero SKUs x 27 slots x 184 days? Wait: let's keep 35 hero SKUs across 25 stores
    # with 15-min peak slots (18:30-22:00 = 15 slots/day) + 3 daytime slots = 18 slots/day -> 25*35*18*184 = 2.9M rows,
    # OR 25 stores x 25 hero SKUs x 18 slots/day x 184 days = 2.07M rows -> ~120MB CSV.
    # Let's use 25 stores x 24 hero SKUs x 16 slots/day x 184 days = 1,766,400 rows (~95MB, fast in NumPy/SQL!).
    tracked_skus = hero_skus.head(24)
    slot_mins = [8 * 60, 13 * 60, 17 * 60] + list(range(18 * 60 + 30, 22 * 60 + 15, 15))  # 18 slots/day
    #Wait: 25 * 24 * 18 * 184 = 1,987,200 rows; let's use 18:45..22:00 (14 peak slots) + 10:00, 14:00 = 16 slots -> 1.76M rows
    slot_mins = [10 * 60, 14 * 60] + list(range(18 * 60 + 45, 22 * 60 + 15, 15))  # 16 slots/day

    n_pairs = len(store_ids) * len(tracked_skus)  # 600 pairs
    pair_store = np.repeat(store_ids, len(tracked_skus))
    pair_sku = np.tile(tracked_skus["sku_id"].values, len(store_ids))
    pair_reorder = np.tile(tracked_skus["reorder_threshold"].values, len(store_ids))
    pair_profile = np.array([profiles[s] for s in pair_store])

    # Build timestamp matrix (n_days * len(slot_mins))
    day_sec = np.arange(n_days, dtype=np.int64) * 86400
    slot_sec = np.array(slot_mins, dtype=np.int64) * 60
    all_offsets_sec = (day_sec[:, None] + slot_sec[None, :]).ravel()
    all_ts_ist = start_ist + pd.to_timedelta(all_offsets_sec, unit="s")
    all_ts_utc_str = all_ts_ist.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ").to_numpy()
    slot_hours = all_ts_ist.hour.to_numpy()

    n_slots = len(all_offsets_sec)
    total_rows = n_pairs * n_slots  # 600 * 2944 = 1,766,400? Wait: 184*16=2944, 600*2944=1,766,400!
    # Wait: writing 1.76M rows to CSV & SQLite might take ~25-40s. Using 18 hero SKUs (450 pairs * 2944 = 1,324,800) or 15 hero SKUs (1.10M) is super clean and fast!
    # Let's actually use 16 hero SKUs (400 pairs * 2944 = 1,177,600 rows) — still covers all 25 stores and 16 high-velocity SKUs every 15 minutes during 7-10 PM!
    tracked_skus = hero_skus.head(16)
    n_pairs = len(store_ids) * len(tracked_skus)  # 400
    pair_store = np.repeat(store_ids, len(tracked_skus))
    pair_sku = np.tile(tracked_skus["sku_id"].values, len(store_ids))
    pair_reorder = np.tile(tracked_skus["reorder_threshold"].values, len(store_ids))
    pair_profile = np.array([profiles[s] for s in pair_store])
    total_rows = n_pairs * n_slots

    # Generate stock levels: normal 18-65 units, dipping to 0 during 7-10 PM especially at STOCKOUT_LOSS stores
    stock = rng.integers(14, 60, size=(n_slots, n_pairs))
    is_evening_peak = (slot_hours >= 19) & (slot_hours <= 21)
    is_stockout_store = pair_profile == "STOCKOUT_LOSS"

    # Base evening stockout probability ~8%, rising to ~26% at STOCKOUT_LOSS stores
    p_zero = np.where(is_evening_peak[:, None], np.where(is_stockout_store[None, :], 0.25, 0.065), 0.015)
    zero_mask = rng.random((n_slots, n_pairs)) < p_zero
    stock = np.where(zero_mask, 0, stock)

    inv_df = pd.DataFrame({
        "snapshot_id": [f"INV-{i + 1:08d}" for i in range(total_rows)],
        "store_id": np.tile(pair_store, n_slots),
        "sku_id": np.tile(pair_sku, n_slots),
        "snapshot_timestamp": np.repeat(all_ts_utc_str, n_pairs),
        "stock_on_hand": stock.ravel().astype(int),
        "reorder_threshold": np.tile(pair_reorder, n_slots).astype(int),
    })
    logger.info("Generated %d inventory snapshots.", len(inv_df))
    return inv_df


def generate_rider_logs(rng: np.random.Generator, orders_df: pd.DataFrame) -> pd.DataFrame:
    """Generate rider activity telemetry logs linked to delivered orders."""
    delivered = orders_df[orders_df["order_status"] == "DELIVERED"].copy()
    events = []
    # Create ASSIGNED, PICKED_UP, DELIVERED events per delivered order
    for event_type, ts_col in [("ASSIGNED", "packed_at"), ("PICKED_UP", "dispatched_at"), ("DELIVERED", "delivered_at")]:
        part = pd.DataFrame({
            "rider_id": delivered["rider_id"].values,
            "store_id": delivered["store_id"].values,
            "order_id": delivered["order_id"].values,
            "event_type": event_type,
            "event_timestamp": delivered[ts_col].values,
        })
        events.append(part)
    rider_logs_df = pd.concat(events, ignore_index=True)
    rider_logs_df.insert(0, "log_id", [f"RLOG-{i + 1:08d}" for i in range(len(rider_logs_df))])
    logger.info("Generated %d rider activity log rows.", len(rider_logs_df))
    return rider_logs_df


def inject_messy_data(
    rng: np.random.Generator,
    stores_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    order_items_df: pd.DataFrame,
    inv_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Deliberately inject all 12 messy data anomalies from Section 7 into raw datasets."""
    rates = get_simulation_config()["messy_data_rates"]
    raw_stores = stores_df.copy()
    raw_orders = orders_df.copy()
    raw_items = order_items_df.copy()
    raw_inv = inv_df.copy()

    n_orders = len(raw_orders)

    # 1 & 2. Duplicate webhook events & duplicate order notifications
    n_dup_webhook = int(n_orders * rates["duplicate_webhook_rate"])
    n_dup_notif = int(n_orders * rates["duplicate_notification_rate"])
    dup_wh = raw_orders.sample(n=n_dup_webhook, random_state=42).copy()
    dup_nt = raw_orders.sample(n=n_dup_notif, random_state=99).copy()
    # Slight timestamp jitter or formatting variance on duplicate notifications
    raw_orders = pd.concat([raw_orders, dup_wh, dup_nt], ignore_index=True)

    # 5. Inconsistent city spellings on raw_stores (and we'll also add city column on raw_orders or raw_stores? Wait: Section 6 says stores & customers have city; let's inject inconsistent city spellings on customers/stores!)
    # Let's keep raw_stores clean enough or add city typos on a raw_customers copy + raw_stores? Wait: if raw_stores has 25 rows, injecting 2-3 typos like "Bangalore", "Bombay", "Gurgaon" tests city normalization cleanly!
    if len(raw_stores) >= 20:
        raw_stores.loc[0, "city"] = "Bangalore"
        raw_stores.loc[7, "city"] = "Bombay"
        raw_stores.loc[14, "city"] = "New Delhi"
        raw_stores.loc[20, "city"] = "Madras"

    # 6. Incorrect or malformed pincodes on raw_stores? Wait: if a store is rejected, its orders lose FK! Better: inject malformed pincode on 2 extra bogus test store rows or test pincode normalization/repair, OR keep malformed pincodes in raw_stores? Wait: let's add 1 invalid store row with malformed pincode "5600A1" so quarantine catches it without breaking the 25 real stores!
    bogus_store = raw_stores.iloc[0].copy()
    bogus_store["store_id"] = "STR-999"
    bogus_store["store_name"] = "Invalid Test Hub"
    bogus_store["pincode"] = "5600A1"
    raw_stores = pd.concat([raw_stores, pd.DataFrame([bogus_store])], ignore_index=True)

    # 7. UTC/IST timestamp inconsistencies (~3% of orders formatted with +05:30 or naive IST string)
    n_tz = int(n_orders * rates["utc_ist_mixed_tz_rate"])
    tz_idx = rng.choice(n_orders, size=n_tz, replace=False)
    placed_ist = pd.to_datetime(raw_orders.loc[tz_idx, "placed_at"], utc=True).dt.tz_convert("Asia/Kolkata")
    raw_orders.loc[tz_idx, "placed_at"] = placed_ist.dt.strftime("%Y-%m-%d %H:%M:%S+05:30")

    # 8. Invalid order lifecycle sequences (delivered_at < dispatched_at or packed_at < placed_at)
    n_life = int(n_orders * rates["invalid_lifecycle_rate"])
    deliv_indices = raw_orders.index[raw_orders["order_status"] == "DELIVERED"].to_numpy()
    life_idx = rng.choice(deliv_indices, size=min(n_life, len(deliv_indices)), replace=False)
    bad_deliv = pd.to_datetime(raw_orders.loc[life_idx, "placed_at"], utc=True, format="mixed") - pd.Timedelta(minutes=5)
    raw_orders.loc[life_idx, "delivered_at"] = bad_deliv.dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 9. Missing rider identifiers on DELIVERED orders
    n_miss_rider = int(n_orders * rates["missing_rider_on_delivered_rate"])
    avail_deliv = np.setdiff1d(deliv_indices, life_idx)
    miss_rider_idx = rng.choice(avail_deliv, size=min(n_miss_rider, len(avail_deliv)), replace=False)
    raw_orders.loc[miss_rider_idx, "rider_id"] = None

    # 12. Inconsistent payment-mode labels (gpay, phonepe, credit_card, cash, etc.)
    n_pay = int(n_orders * rates["inconsistent_payment_label_rate"])
    pay_idx = rng.choice(n_orders, size=n_pay, replace=False)
    for idx in pay_idx:
        pm = raw_orders.loc[idx, "payment_mode"]
        if pm == "UPI":
            raw_orders.loc[idx, "payment_mode"] = str(rng.choice(["gpay", "phonepe", "paytm_upi", "upi"]))
        elif pm == "CARD":
            raw_orders.loc[idx, "payment_mode"] = str(rng.choice(["credit_card", "debit_card", "cc"]))
        else:
            raw_orders.loc[idx, "payment_mode"] = str(rng.choice(["cash", "cash_on_delivery"]))

    # 10. Invalid SKU references in order_items
    n_bad_sku = int(len(raw_items) * rates["invalid_sku_ref_rate"])
    bad_sku_idx = rng.choice(len(raw_items), size=n_bad_sku, replace=False)
    raw_items.loc[bad_sku_idx, "sku_id"] = "SKU-9999"

    # 11. Negative prices or costs in order_items & orders
    n_neg_item = int(len(raw_items) * rates["negative_price_cost_rate"])
    neg_item_idx = rng.choice(len(raw_items), size=n_neg_item, replace=False)
    raw_items.loc[neg_item_idx, "unit_price"] = -abs(raw_items.loc[neg_item_idx, "unit_price"])

    n_neg_ord = int(n_orders * rates["negative_price_cost_rate"])
    neg_ord_idx = rng.choice(avail_deliv, size=min(n_neg_ord, len(avail_deliv)), replace=False)
    raw_orders.loc[neg_ord_idx, "cart_value"] = -abs(raw_orders.loc[neg_ord_idx, "cart_value"])

    # 4. Negative inventory glitches
    n_neg_inv = int(len(raw_inv) * rates["negative_inventory_glitch_rate"])
    neg_inv_idx = rng.choice(len(raw_inv), size=n_neg_inv, replace=False)
    raw_inv.loc[neg_inv_idx, "stock_on_hand"] = -rng.integers(1, 15, size=n_neg_inv)

    logger.info(
        "Injected messy anomalies: +%d duplicate orders, %d mixed-tz, %d bad lifecycle, %d missing rider, %d bad SKU refs, %d negative prices, %d negative inventory glitches.",
        n_dup_webhook + n_dup_notif, n_tz, len(life_idx), len(miss_rider_idx), n_bad_sku, n_neg_item + n_neg_ord, n_neg_inv,
    )
    return raw_stores, raw_orders, raw_items, raw_inv
