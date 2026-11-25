-- ============================================================================
-- QuickCommerceIQ — Delivery SLA Decomposition, Rolling 30-Min & Bottlenecks
-- Target SLA: 12 minutes (720 seconds)
-- ============================================================================

-- 1. Store-Level SLA Decomposition & Bottleneck Classification (CTEs + RANK)
WITH delivered AS (
    SELECT
        fo.order_id,
        ds.store_id,
        ds.store_name,
        ds.city,
        dt.hour_ist,
        fo.placed_at,
        fo.weather_tag,
        fo.picking_seconds / 60.0                           AS picking_min,
        fo.assignment_seconds / 60.0                        AS assignment_min,
        fo.transit_seconds / 60.0                           AS transit_min,
        fo.total_delivery_seconds / 60.0                    AS total_min,
        fo.is_sla_breach
    FROM dw.fact_orders fo
    JOIN dw.dim_dark_stores ds ON fo.store_sk = ds.store_sk
    JOIN dw.dim_date_time dt ON fo.date_time_sk = dt.date_time_sk
    WHERE fo.order_status = 'DELIVERED'
),
store_sla AS (
    SELECT
        store_id,
        store_name,
        city,
        COUNT(*)                                            AS delivered_orders,
        ROUND(AVG(total_min)::NUMERIC, 2)                   AS avg_delivery_min,
        ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_min)::NUMERIC, 2) AS p50_delivery_min,
        ROUND(PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY total_min)::NUMERIC, 2) AS p90_delivery_min,
        ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_min)::NUMERIC, 2) AS p95_delivery_min,
        ROUND(AVG(picking_min)::NUMERIC, 2)                 AS avg_picking_min,
        ROUND(AVG(assignment_min)::NUMERIC, 2)              AS avg_assignment_min,
        ROUND(AVG(transit_min)::NUMERIC, 2)                 AS avg_transit_min,
        ROUND(100.0 * AVG(CASE WHEN is_sla_breach THEN 1.0 ELSE 0.0 END), 2) AS sla_breach_pct
    FROM delivered
    GROUP BY store_id, store_name, city
)
SELECT
    *,
    RANK() OVER (ORDER BY sla_breach_pct DESC)              AS worst_sla_rank,
    CASE
        WHEN (avg_picking_min - 2.5) >= GREATEST(avg_assignment_min - 2.0, avg_transit_min - 5.5) THEN 'PICKING'
        WHEN (avg_assignment_min - 2.0) >= GREATEST(avg_picking_min - 2.5, avg_transit_min - 5.5) THEN 'RIDER_ASSIGNMENT'
        ELSE 'TRANSIT'
    END                                                     AS primary_bottleneck
FROM store_sla
ORDER BY sla_breach_pct DESC;

-- 2. Hourly SLA Breach % with LAG comparison
WITH hourly_sla AS (
    SELECT
        dt.hour_ist,
        COUNT(*)                                            AS delivered_orders,
        ROUND(100.0 * AVG(CASE WHEN fo.is_sla_breach THEN 1.0 ELSE 0.0 END), 2) AS sla_breach_pct,
        ROUND(AVG(fo.picking_seconds / 60.0)::NUMERIC, 2)   AS avg_picking_min,
        ROUND(AVG(fo.assignment_seconds / 60.0)::NUMERIC, 2) AS avg_assignment_min,
        ROUND(AVG(fo.transit_seconds / 60.0)::NUMERIC, 2)   AS avg_transit_min
    FROM dw.fact_orders fo
    JOIN dw.dim_date_time dt ON fo.date_time_sk = dt.date_time_sk
    WHERE fo.order_status = 'DELIVERED'
    GROUP BY dt.hour_ist
)
SELECT
    hour_ist,
    delivered_orders,
    sla_breach_pct,
    ROUND(sla_breach_pct - LAG(sla_breach_pct) OVER (ORDER BY hour_ist), 2) AS breach_pct_delta_vs_prev_hour,
    avg_picking_min,
    avg_assignment_min,
    avg_transit_min
FROM hourly_sla
ORDER BY hour_ist;

-- 3. Rolling 30-Minute Operational Windows per Store (PostgreSQL RANGE INTERVAL)
SELECT
    ds.store_id,
    fo.placed_at,
    COUNT(*) OVER (
        PARTITION BY ds.store_id
        ORDER BY fo.placed_at
        RANGE BETWEEN INTERVAL '30 minutes' PRECEDING AND CURRENT ROW
    )                                                       AS rolling_30m_order_load,
    ROUND(AVG(fo.total_delivery_seconds / 60.0) OVER (
        PARTITION BY ds.store_id
        ORDER BY fo.placed_at
        RANGE BETWEEN INTERVAL '30 minutes' PRECEDING AND CURRENT ROW
    )::NUMERIC, 2)                                          AS rolling_30m_avg_delivery_min
FROM dw.fact_orders fo
JOIN dw.dim_dark_stores ds ON fo.store_sk = ds.store_sk
WHERE fo.order_status = 'DELIVERED'
ORDER BY ds.store_id, fo.placed_at
LIMIT 500;
