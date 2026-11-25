# QuickCommerceIQ — Warehouse Data Dictionary

## Dimension Tables (`dw.*`)

### `dw.dim_dark_stores` (SCD Type 2)
| Column | Type | Description |
|---|---|---|
| `store_sk` | `BIGINT` (PK) | Surrogate key |
| `store_id` | `VARCHAR(20)` | Natural business key (`STR-001`..`STR-025`) |
| `store_name` | `VARCHAR(120)` | Dark store hub name and city |
| `city`, `state`, `zone` | `VARCHAR` | Standardized metro (`Bengaluru`, `Mumbai`, `Delhi NCR`, `Chennai`) |
| `pincode` | `CHAR(6)` | Validated 6-digit Indian pincode |
| `rent_tier` | `VARCHAR(20)` | `PREMIUM`, `HIGH_STREET`, `STANDARD` |
| `monthly_rent` | `NUMERIC(12,2)` | Monthly lease cost in INR (₹) |
| `operating_capacity` | `INTEGER` | Target hourly order capacity |
| `staffing_level` | `INTEGER` | Pickers assigned per shift |
| `effective_from`, `effective_to`, `is_current` | `TIMESTAMPTZ` / `BOOLEAN` | SCD Type 2 validity interval |

### `dw.dim_skus` (SCD Type 2)
| Column | Type | Description |
|---|---|---|
| `sku_sk` | `BIGINT` (PK) | Surrogate key |
| `sku_id` | `VARCHAR(20)` | Business key (`SKU-0001`..`SKU-0650`) |
| `sku_name`, `category`, `subcategory` | `VARCHAR` | Product taxonomy across 8 grocery categories |
| `unit_cost`, `selling_price` | `NUMERIC(12,2)` | Point-in-time procurement cost and selling price (₹) |
| `gross_margin`, `gross_margin_pct` | `NUMERIC` | Unit margin amount (₹) and percentage |
| `reorder_threshold` | `INTEGER` | Replenishment trigger threshold |
| `effective_from`, `effective_to`, `is_current` | `TIMESTAMPTZ` / `BOOLEAN` | SCD Type 2 validity interval |

### `dw.dim_customers`, `dw.dim_riders`, `dw.dim_date_time`
- `dim_customers`: `customer_sk`, `customer_id`, `acquisition_channel`, `customer_segment`, `city`, `home_store_id`, `registration_date`, `first_order_date`.
- `dim_riders`: `rider_sk`, `rider_id`, `vehicle_type`, `employment_type`, `payout_tier`, `assigned_store_id`, `availability_status`.
- `dim_date_time`: Hourly IST grain (`date_time_sk = YYYYMMDDHH`), `full_date`, `year_month`, `hour_ist`, `time_bucket`, `is_weekend`, `is_peak_evening`.

## Fact Tables (`dw.*`)

### `dw.fact_orders` (Grain: 1 row per order)
- Foreign keys: `customer_sk`, `store_sk` (SCD2), `rider_sk` (nullable for cancelled), `date_time_sk`.
- Lifecycle UTC timestamps: `placed_at`, `packed_at`, `dispatched_at`, `delivered_at`, `cancelled_at`.
- Financial columns (INR): `cart_value`, `discounts`, `delivery_fee`, `handling_fee`, `surge_fee`, `gross_margin`, `rider_payout`, `packaging_cost`, `refund_cost`, `net_contribution_margin`.
- SLA columns: `picking_seconds`, `assignment_seconds`, `transit_seconds`, `total_delivery_seconds`, `is_sla_breach`.

### `dw.fact_order_items` (Grain: 1 row per order-SKU)
- Foreign keys: `order_sk -> fact_orders`, `sku_sk -> dim_skus` (SCD2).
- Preserved financials: `quantity`, `historical_unit_price`, `historical_unit_cost`, `line_total`, `line_gross_margin`.

### `dw.fact_inventory_snapshots` (Grain: 1 row per store-SKU-timestamp)
- `snapshot_sk`, `snapshot_id`, `store_sk`, `sku_sk`, `snapshot_timestamp`, `stock_on_hand`, `reorder_threshold`, `is_stockout`.

### `dw.fact_ab_experiment_events` (Grain: 1 row per customer experiment event)
- `event_sk`, `event_id`, `customer_sk`, `order_sk` (nullable for `CART_ABANDONED`), `experiment_name`, `variant`, `event_type`, `cart_value`, `net_contribution`, `event_timestamp`.
