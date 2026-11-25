-- ============================================================================
-- QuickCommerceIQ — Performance Indexes for Analytical & Power BI Workloads
-- ============================================================================

-- Dimension lookup indexes
CREATE INDEX IF NOT EXISTS idx_dim_dark_stores_bk_curr
    ON dw.dim_dark_stores (store_id, is_current);

CREATE INDEX IF NOT EXISTS idx_dim_skus_bk_curr
    ON dw.dim_skus (sku_id, is_current);

CREATE INDEX IF NOT EXISTS idx_dim_customers_city_seg
    ON dw.dim_customers (city, customer_segment);

CREATE INDEX IF NOT EXISTS idx_dim_date_time_date_hour
    ON dw.dim_date_time (full_date, hour_ist);

-- Fact Orders analytical indexes
CREATE INDEX IF NOT EXISTS idx_fact_orders_placed_at
    ON dw.fact_orders (placed_at);

CREATE INDEX IF NOT EXISTS idx_fact_orders_store_dt
    ON dw.fact_orders (store_sk, date_time_sk);

CREATE INDEX IF NOT EXISTS idx_fact_orders_cust_status
    ON dw.fact_orders (customer_sk, order_status);

CREATE INDEX IF NOT EXISTS idx_fact_orders_weather_status
    ON dw.fact_orders (weather_tag, order_status);

-- Fact Order Items indexes
CREATE INDEX IF NOT EXISTS idx_fact_order_items_order_sk
    ON dw.fact_order_items (order_sk);

CREATE INDEX IF NOT EXISTS idx_fact_order_items_sku_sk
    ON dw.fact_order_items (sku_sk);

-- Fact Inventory Snapshots indexes (for 7-10 PM stockout window analysis)
CREATE INDEX IF NOT EXISTS idx_fact_inv_store_sku_ts
    ON dw.fact_inventory_snapshots (store_sk, sku_sk, snapshot_timestamp);

CREATE INDEX IF NOT EXISTS idx_fact_inv_stockout_ts
    ON dw.fact_inventory_snapshots (is_stockout, snapshot_timestamp)
    WHERE is_stockout = TRUE;

-- A/B Experiment Events indexes
CREATE INDEX IF NOT EXISTS idx_fact_ab_events_exp_var
    ON dw.fact_ab_experiment_events (experiment_name, variant, event_type);

CREATE INDEX IF NOT EXISTS idx_fact_ab_events_cust
    ON dw.fact_ab_experiment_events (customer_sk);

-- Audit / Quarantine indexes
CREATE INDEX IF NOT EXISTS idx_quarantine_batch_entity
    ON audit.data_quarantine (batch_id, entity_type);
