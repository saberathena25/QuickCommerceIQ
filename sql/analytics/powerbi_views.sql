-- ============================================================================
-- QuickCommerceIQ — Power BI Optimized PostgreSQL Analytical Views
-- Connect Power BI Desktop via PostgreSQL connector -> Schema: bi
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS bi;

-- 1. Star Schema Fact View: Orders Enriched (IST timestamps + SLA + NCM)
CREATE OR REPLACE VIEW bi.vw_fact_orders_enriched AS
SELECT
    fo.order_sk,
    fo.order_id,
    fo.customer_sk,
    fo.store_sk,
    fo.rider_sk,
    fo.date_time_sk,
    (fo.placed_at AT TIME ZONE 'Asia/Kolkata')              AS placed_at_ist,
    DATE(fo.placed_at AT TIME ZONE 'Asia/Kolkata')          AS order_date_ist,
    EXTRACT(HOUR FROM (fo.placed_at AT TIME ZONE 'Asia/Kolkata'))::INT AS hour_ist,
    fo.order_status,
    fo.payment_mode,
    fo.weather_tag,
    fo.cart_value,
    fo.discounts,
    fo.delivery_fee,
    fo.handling_fee,
    fo.surge_fee,
    fo.gross_margin,
    fo.rider_payout,
    fo.packaging_cost,
    fo.refund_cost,
    fo.net_contribution_margin,
    ROUND(fo.picking_seconds / 60.0, 2)                     AS picking_minutes,
    ROUND(fo.assignment_seconds / 60.0, 2)                  AS assignment_minutes,
    ROUND(fo.transit_seconds / 60.0, 2)                     AS transit_minutes,
    ROUND(fo.total_delivery_seconds / 60.0, 2)              AS total_delivery_minutes,
    fo.is_sla_breach
FROM dw.fact_orders fo;

-- 2. Current Store Dimension View (SCD Type 2 active slice for slicers)
CREATE OR REPLACE VIEW bi.vw_dim_dark_stores_current AS
SELECT
    store_sk,
    store_id,
    store_name,
    city,
    state,
    pincode,
    zone,
    rent_tier,
    monthly_rent,
    operating_capacity,
    staffing_level
FROM dw.dim_dark_stores
WHERE is_current = TRUE;

-- 3. Pre-Aggregated Store Executive Scoreboard View (Page 1 & Page 2)
CREATE OR REPLACE VIEW bi.vw_store_executive_summary AS
WITH store_base AS (
    SELECT
        ds.store_id,
        MAX(ds.store_name)                                  AS store_name,
        MAX(ds.city)                                        AS city,
        MAX(ds.zone)                                        AS zone,
        MAX(ds.monthly_rent)                                AS monthly_rent,
        COUNT(*)                                            AS total_orders,
        COUNT(*) FILTER (WHERE fo.order_status = 'DELIVERED') AS delivered_orders,
        ROUND(SUM(fo.cart_value), 2)                        AS total_gmv_inr,
        ROUND(SUM(fo.net_contribution_margin), 2)           AS total_ncm_inr,
        ROUND(AVG(fo.net_contribution_margin), 2)           AS avg_ncm_per_order_inr,
        ROUND(AVG(fo.rider_payout), 2)                      AS avg_rider_payout_inr,
        ROUND(AVG(fo.discounts), 2)                         AS avg_discount_inr,
        ROUND(AVG(fo.refund_cost), 2)                       AS avg_refund_inr,
        ROUND(100.0 * AVG(CASE WHEN fo.order_status = 'DELIVERED' AND fo.is_sla_breach THEN 1.0
                               WHEN fo.order_status = 'DELIVERED' THEN 0.0 END), 2) AS sla_breach_pct,
        ROUND(AVG(CASE WHEN fo.order_status = 'DELIVERED' THEN fo.picking_seconds / 60.0 END)::NUMERIC, 2) AS avg_picking_min,
        ROUND(AVG(CASE WHEN fo.order_status = 'DELIVERED' THEN fo.assignment_seconds / 60.0 END)::NUMERIC, 2) AS avg_assignment_min,
        ROUND(AVG(CASE WHEN fo.order_status = 'DELIVERED' THEN fo.transit_seconds / 60.0 END)::NUMERIC, 2) AS avg_transit_min,
        ROUND(AVG(CASE WHEN fo.order_status = 'DELIVERED' THEN fo.total_delivery_seconds / 60.0 END)::NUMERIC, 2) AS avg_delivery_min
    FROM dw.fact_orders fo
    JOIN dw.dim_dark_stores ds ON fo.store_sk = ds.store_sk
    GROUP BY ds.store_id
)
SELECT
    *,
    ROUND(total_ncm_inr - (monthly_rent * 6 * 1.15), 2)     AS net_store_operating_profit_6m_inr,
    CASE
        WHEN (avg_picking_min - 2.5) >= GREATEST(avg_assignment_min - 2.0, avg_transit_min - 5.5) THEN 'PICKING'
        WHEN (avg_assignment_min - 2.0) >= GREATEST(avg_picking_min - 2.5, avg_transit_min - 5.5) THEN 'RIDER_ASSIGNMENT'
        ELSE 'TRANSIT'
    END                                                     AS primary_bottleneck
FROM store_base;

-- 4. Hourly SLA & NCM Heatmap View (Page 2)
CREATE OR REPLACE VIEW bi.vw_hourly_sla_heatmap AS
SELECT
    ds.city,
    ds.store_id,
    dt.hour_ist,
    fo.weather_tag,
    COUNT(*)                                                AS orders,
    COUNT(*) FILTER (WHERE fo.order_status = 'DELIVERED')   AS delivered_orders,
    ROUND(100.0 * AVG(CASE WHEN fo.order_status = 'DELIVERED' AND fo.is_sla_breach THEN 1.0
                           WHEN fo.order_status = 'DELIVERED' THEN 0.0 END), 2) AS sla_breach_pct,
    ROUND(AVG(fo.picking_seconds / 60.0)::NUMERIC, 2)       AS avg_picking_min,
    ROUND(AVG(fo.assignment_seconds / 60.0)::NUMERIC, 2)    AS avg_assignment_min,
    ROUND(AVG(fo.transit_seconds / 60.0)::NUMERIC, 2)       AS avg_transit_min,
    ROUND(AVG(fo.net_contribution_margin), 2)               AS avg_ncm_inr
FROM dw.fact_orders fo
JOIN dw.dim_dark_stores ds ON fo.store_sk = ds.store_sk
JOIN dw.dim_date_time dt ON fo.date_time_sk = dt.date_time_sk
GROUP BY ds.city, ds.store_id, dt.hour_ist, fo.weather_tag;

-- 5. A/B Experiment Customer-Level ITT View (Page 3)
CREATE OR REPLACE VIEW bi.vw_ab_experiment_itt AS
SELECT
    aa.customer_id,
    aa.experiment_name,
    aa.variant,
    aa.threshold_inr,
    dc.city,
    dc.customer_segment,
    COALESCE(SUM(CASE WHEN fe.event_type = 'ORDER_COMPLETED' THEN 1 ELSE 0 END), 0) AS completed_orders,
    COALESCE(SUM(CASE WHEN fe.event_type = 'CART_ABANDONED' THEN 1 ELSE 0 END), 0) AS abandoned_carts,
    COALESCE(SUM(CASE WHEN fe.event_type IN ('ORDER_COMPLETED', 'ORDER_CANCELLED') THEN fe.net_contribution ELSE 0 END), 0) AS itt_net_contribution_inr,
    COALESCE(AVG(CASE WHEN fe.event_type = 'ORDER_COMPLETED' THEN fe.cart_value END), 0) AS avg_order_value_inr
FROM dw.ab_experiment_assignments aa
JOIN dw.dim_customers dc ON aa.customer_id = dc.customer_id
LEFT JOIN dw.fact_ab_experiment_events fe
  ON dc.customer_sk = fe.customer_sk
 AND aa.experiment_name = fe.experiment_name
GROUP BY aa.customer_id, aa.experiment_name, aa.variant, aa.threshold_inr, dc.city, dc.customer_segment;
