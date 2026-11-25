# QuickCommerceIQ — System Architecture

## 1. End-to-End Data Flow

```mermaid
flowchart TD
    subgraph SRC["Raw Data Sources (Batch / Simulated Streams)"]
        S1["Order Webhooks (1-min cadence)"]
        S2["Rider Activity Logs (1-min cadence)"]
        S3["Inventory Snapshots (15-min peak)"]
        S4["Weather Telemetry (30-min cadence)"]
    end

    subgraph RAW["Raw Landing Layer (data/raw/)"]
        R1["orders.csv, order_items.csv, customers.csv, dark_stores.csv, riders.csv, skus.csv"]
        R2["inventory_snapshots.csv, rider_logs.csv, weather_data.csv, ab_experiment_*.csv"]
    end

    subgraph ETL["Python ETL & Data Quality Gate"]
        E1["Normalization: City/Payment Mapping, Text Cleanup, UTC Standardization"]
        E2["Deduplication & Lifecycle Validation (Delivered vs Cancelled)"]
        E3["Referential Integrity & Financial Checks"]
        E4{"Critical Quality Gate<br/>(Reconciliation & PKs)"}
    end

    subgraph AUDIT["Audit & Quarantine Layer"]
        Q1["data_quarantine (Anomalies + Rejection Reasons)"]
        Q2["reports/data_quality_report.json"]
    end

    subgraph DW["Relational Star Schema Warehouse (PostgreSQL / SQLite Mirror)"]
        D1["Dimensions: dim_dark_stores (SCD2), dim_skus (SCD2), dim_customers, dim_riders, dim_date_time"]
        F1["Facts: fact_orders, fact_order_items, fact_inventory_snapshots, fact_ab_experiment_events"]
    end

    subgraph ANALYTICS["Analytics & Experimentation Engine"]
        A1["Unit Economics (NCM) & Store Profitability"]
        A2["SLA Decomposition & Rolling 30-Min Congestion"]
        A3["Cohort Retention & Peak Stockout Lost GMV"]
        A4["Statistical A/B Testing (SRM, Welch t, Z, Mann-Whitney, Bootstrap)"]
    end

    subgraph OUT["Executive Output Layer"]
        O1["Power BI Views (bi.*) & DAX Measures"]
        O2["Excel Unit Economics Simulator (.xlsx)"]
        O3["Executive Memo PDF & Visual Charts"]
    end

    SRC --> RAW --> E1 --> E2 --> E3 --> E4
    E4 -- "Rejected / Duplicate Rows" --> Q1
    E4 -- "Gate Failed: Abort Load" --> Q2
    E4 -- "Gate Passed: Transactional Load" --> DW
    E4 --> Q2
    DW --> ANALYTICS --> OUT
```

## 2. Refresh Cadence Design (Batch-Configurable Locally)

| Stream / Layer | Target Production Cadence | Local Batch Implementation |
|---|---|---|
| Order Webhooks | Every 1 minute | `python/ingestion/etl_pipeline.py` (idempotent key dedup) |
| Rider Activity Events | Every 1 minute | `fact_rider_logs` batch load |
| Inventory Snapshots | Every 15 minutes | `fact_inventory_snapshots` (15-min peak 18:45–22:00 IST) |
| Weather Telemetry | Every 30 minutes | `fact_weather_observations` (30-min city slots) |
| Financial & SLA Analytics | Hourly | `python/analytics/engine.py` |
| Cohorts & A/B Readout | Daily | `python/experiments/ab_testing.py` |

## 3. Warehouse Design Choices
- **Timezone Standard:** All timestamps are normalized to UTC (`TIMESTAMPTZ`) on ingestion and converted to `Asia/Kolkata` (IST) for reporting and `dim_date_time` keys (`YYYYMMDDHH`).
- **SCD Type 2:** `dim_dark_stores` (rent tier & staffing revisions) and `dim_skus` (supplier cost & MRP changes) maintain `effective_from`, `effective_to`, and `is_current` attributes, while `fact_order_items` persists `historical_unit_price` and `historical_unit_cost` so historical profit never shifts retroactively.
- **Local Portability:** `python/db.py` connects to PostgreSQL (`psycopg` + SQLAlchemy) when configured/running via Docker Compose, and provides a schema-aligned local SQLite mirror (`data/processed/quickcommerce_warehouse.db`) so all analytics and tests run out of the box on Windows 11.
