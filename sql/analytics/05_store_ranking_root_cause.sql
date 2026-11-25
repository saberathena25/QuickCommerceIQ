-- ============================================================================
-- QuickCommerceIQ — Store Performance Ranking & Analytical Root-Cause Tags
-- ============================================================================

WITH store_metrics AS (
    SELECT
        ds.store_id,
        MAX(ds.store_name)                                  AS store_name,
        MAX(ds.city)                                        AS city,
        COUNT(*)                                            AS total_orders,
        ROUND(AVG(fo.net_contribution_margin), 2)           AS avg_ncm_per_order,
        ROUND(SUM(fo.net_contribution_margin), 2)           AS total_order_ncm,
        ROUND(AVG(fo.rider_payout), 2)                      AS avg_rider_cost_per_order,
        ROUND(AVG(fo.refund_cost), 2)                       AS avg_refund_per_order,
        ROUND(100.0 * SUM(fo.discounts) / NULLIF(SUM(fo.cart_value), 0), 2) AS discount_pct_of_gmv,
        ROUND(100.0 * AVG(CASE WHEN fo.order_status = 'DELIVERED' AND fo.is_sla_breach THEN 1.0
                               WHEN fo.order_status = 'DELIVERED' THEN 0.0 END), 2) AS sla_breach_pct,
        ROUND(AVG(CASE WHEN fo.order_status = 'DELIVERED' THEN fo.picking_seconds / 60.0 END)::NUMERIC, 2) AS avg_picking_min,
        ROUND(AVG(CASE WHEN fo.order_status = 'DELIVERED' THEN fo.assignment_seconds / 60.0 END)::NUMERIC, 2) AS avg_assign_min,
        ROUND(AVG(CASE WHEN fo.order_status = 'DELIVERED' THEN fo.transit_seconds / 60.0 END)::NUMERIC, 2) AS avg_transit_min
    FROM dw.fact_orders fo
    JOIN dw.dim_dark_stores ds ON fo.store_sk = ds.store_sk
    GROUP BY ds.store_id
)
SELECT
    *,
    RANK() OVER (ORDER BY avg_ncm_per_order DESC)           AS profitability_rank,
    RANK() OVER (ORDER BY sla_breach_pct ASC)               AS sla_rank,
    CONCAT_WS(', ',
        CASE WHEN avg_rider_cost_per_order > 38.0 THEN 'HIGH_RIDER_COST' END,
        CASE WHEN avg_picking_min > 4.0          THEN 'PICKING_BOTTLENECK' END,
        CASE WHEN avg_assign_min > 3.2           THEN 'RIDER_SHORTAGE' END,
        CASE WHEN avg_transit_min > 7.5          THEN 'TRANSIT_DELAY' END,
        CASE WHEN discount_pct_of_gmv > 11.5     THEN 'HIGH_DISCOUNT_BURN' END,
        CASE WHEN avg_refund_per_order > 4.5     THEN 'HIGH_REFUND_COST' END
    )                                                       AS analytical_root_causes
FROM store_metrics
ORDER BY avg_ncm_per_order ASC;
