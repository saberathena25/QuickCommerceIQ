# QuickCommerceIQ — Power BI Executive Dashboard Documentation

> **Environment Note:** Power BI Desktop (`pbidesktop.exe`) is not installed on the local build machine, so no binary `.pbix` file was fabricated. Instead, this folder provides the complete **PostgreSQL `bi.*` analytical views** ([powerbi_views.sql](../sql/analytics/powerbi_views.sql)), **DAX measures** ([dax_measures.md](dax_measures.md)), **Star Schema relationship model**, **pre-aggregated CSVs** (`data/processed/analytics_*.csv`), and step-by-step **Power BI Desktop import instructions**.

---

## 1. Star Schema Data Model & Relationships

| Relationship | From Table (Many) | To Table (One) | Cardinality | Cross-Filter |
|---|---|---|---|---|
| Orders → Dark Stores | `fact_orders[store_sk]` | `dim_dark_stores[store_sk]` | Many-to-One | Single |
| Orders → Customers | `fact_orders[customer_sk]` | `dim_customers[customer_sk]` | Many-to-One | Single |
| Orders → Riders | `fact_orders[rider_sk]` | `dim_riders[rider_sk]` | Many-to-One | Single |
| Orders → Date/Time | `fact_orders[date_time_sk]` | `dim_date_time[date_time_sk]` | Many-to-One | Single |
| Order Items → Orders | `fact_order_items[order_sk]` | `fact_orders[order_sk]` | Many-to-One | Single |
| Order Items → SKUs | `fact_order_items[sku_sk]` | `dim_skus[sku_sk]` | Many-to-One | Single |
| Stockouts → Stores | `analytics_stockout_store_sku_hour[store_id]` | `vw_dim_dark_stores_current[store_id]` | Many-to-One | Single |

---

## 2. Visual Design System

- **Canvas:** `1280 × 720` (16:9), light neutral background (`#F8FAFC`), white visual cards (`#FFFFFF`) with `1px solid #E2E8F0` borders.
- **Header Bar:** Dark Navy (`#1B2A4A`) with crisp white Segoe UI Semibold titles.
- **Semantic Palette:**
  - Positive Profitability / SLA Pass: Forest Green (`#166534`)
  - Negative Profitability / SLA Breach: Crimson Red (`#991B1B`)
  - Operational Warning / Monsoon: Amber (`#D97706`)
  - Primary Neutral Accent: Slate Teal (`#0F766E`) & Steel Blue (`#1D4ED8`)
- **Number Formatting:** All INR fields use `"₹"#,##,##0.00` (or Lakhs/Crores custom format strings).

---

## 3. Page Specifications

### Page 1: Executive Landing Dashboard (`CEO / COO / Finance`)
- **Top Slicer Bar:** Date (`full_date`), City (`city`), Dark Store (`store_name`), Weather (`weather_tag`), Payment Mode (`payment_mode`).
- **5 KPI Cards:**
  1. `Total Orders` (`174,288`)
  2. `NCM per Order (INR)` (`₹6.42`, with May `+₹19.48` → Oct `-₹3.27` sparkline/callout)
  3. `SLA Breach Rate %` (`49.86%`)
  4. `Average Delivery Time (Min)` (`12.47 min`)
  5. `Estimated Lost GMV (INR)` (`₹64,451` across tracked hero SKUs 7–10 PM)
- **Visuals:**
  - **Combo Line + Bar Chart:** Daily Orders (bars) vs Daily Avg NCM/Order (line with `₹0` reference line).
  - **Waterfall Chart:** Order-Level Unit Economics Bridge (`Gross Margin` + `Handling` + `Delivery` + `Surge` - `Discounts` - `Rider Payout` - `Packaging` - `Refunds` = `NCM`).
  - **Horizontal Bar Chart:** Bottom 10 Bleeding Stores by Avg NCM/Order (Red for negative, Green/Amber for near-zero).
  - **Matrix Table:** Store-level Root-Cause Diagnostics (`store_name`, `city`, `total_orders`, `avg_ncm_per_order_inr`, `net_store_operating_profit_6m_inr`, `sla_breach_pct`, `root_cause_tags`).

### Page 2: Operations & SLA Deep-Dive (`VP Operations / City Heads`)
- **Matrix Heatmap:** Hour of Day (IST 0–23) × City showing `SLA Breach Rate %` (conditional color scale green → amber → red, highlighting 7–10 PM peak up to `75.16%`).
- **Stacked Bar Chart:** Delivery Stage Decomposition (`Avg Picking Min` + `Avg Rider Assignment Min` + `Avg Transit Min`) by Store & City against `12.0 min` reference line.
- **Clustered Column Chart:** Normal vs Monsoon vs Heavy Rain comparison (`SLA Breach Rate %`, `Avg Delivery Min`, `Avg Rider Payout`, `Avg NCM`).
- **Evening Stockout Matrix & Top-15 SKU Lost GMV Table:** From `analytics_stockout_store_sku_hour.csv` filtered to hours `19, 20, 21`.
- **Operational Exceptions Table:** Stores exceeding `45%` SLA breach or `₹36` rider payout with `primary_bottleneck`.

### Page 3: Growth, Cohorts & A/B Test Readout (`Head of Growth / Data Science`)
- **Cohort Retention Heatmap Matrix:** `cohort_month` (rows) × `month_number` 0–6 (columns) displaying `Cohort Retention %`, split or filterable by `sla_segment` (`FAST <12m`, `MEDIUM 12-20m`, `SLOW >20m`).
- **Line Chart:** Month 0–6 Retention Curves comparing `FAST` vs `MEDIUM` vs `SLOW` first-order SLA segments.
- **A/B Experiment Readout Cards & Clustered Comparison (`₹199 Control` vs `₹249 Treatment`):**
  - SRM Chi-Square Badge (`χ² = 1.42`, `p = 0.234` — PASS)
  - Primary Metric: `NPPU` (`-₹4.87` vs `+₹0.85`, `+₹5.72/user`, `p < 0.0001`, 95% Bootstrap CI `[+₹4.98, +₹6.49]`)
  - Secondary Metrics: `Conversion Rate` (`67.92%` vs `67.33%`), `AOV` (`₹265.04` vs `₹273.30`, `+₹8.26`), `Orders/Customer` (`1.56` vs `1.52`)
  - Guardrail Status Cards: `Cart Abandonment` (`+2.32pp` — PASS), `30-Day Repeat Rate` (`-1.97pp` — BREACHED `-1.50pp` floor)
  - Executive Decision Banner: **`TARGETED_ROLLOUT_OR_229_TEST`**

---

## 4. Import Instructions (Power BI Desktop on Windows 11)

1. Start local PostgreSQL via `docker compose up -d` and run `python run_pipeline.py` (or import the pre-built CSVs directly from `data/processed/analytics_*.csv` & `reports/experiment_results.csv`).
2. Open **Power BI Desktop** → **Get Data** → **PostgreSQL database** (Server: `localhost:5432`, Database: `quickcommerce_iq`).
3. Select views under `bi.*` (`vw_fact_orders_enriched`, `vw_dim_dark_stores_current`, `vw_store_executive_summary`, `vw_hourly_sla_heatmap`, `vw_ab_experiment_itt`) plus `dw.dim_date_time`, `dw.dim_customers`, `dw.dim_skus`, `dw.fact_order_items`.
4. Also import `data/processed/analytics_stockout_store_sku_hour.csv`, `data/processed/analytics_cohort_retention_matrix.csv`, and `reports/experiment_results.csv` (or create SQL views for them).
5. Configure the Star Schema relationships in **Model View** and copy the DAX measures from [dax_measures.md](dax_measures.md).
