-- ============================================================================
-- QuickCommerceIQ — Customer Cohort Retention by First-Order Delivery SLA
-- Delivered orders ONLY for retention activity.
-- ============================================================================

WITH customer_first_order AS (
    SELECT
        fo.customer_sk,
        MIN(fo.placed_at)                                   AS first_placed_at
    FROM dw.fact_orders fo
    WHERE fo.order_status = 'DELIVERED'
    GROUP BY fo.customer_sk
),
first_order_sla AS (
    SELECT
        cfo.customer_sk,
        DATE_TRUNC('month', cfo.first_placed_at AT TIME ZONE 'Asia/Kolkata')::DATE AS cohort_month,
        CASE
            WHEN fo.total_delivery_seconds < 720  THEN 'FAST (<12m)'
            WHEN fo.total_delivery_seconds <= 1200 THEN 'MEDIUM (12-20m)'
            ELSE 'SLOW (>20m)'
        END                                                 AS sla_segment
    FROM customer_first_order cfo
    JOIN dw.fact_orders fo
      ON fo.customer_sk = cfo.customer_sk
     AND fo.placed_at = cfo.first_placed_at
     AND fo.order_status = 'DELIVERED'
),
customer_monthly_activity AS (
    SELECT DISTINCT
        fo.customer_sk,
        DATE_TRUNC('month', fo.placed_at AT TIME ZONE 'Asia/Kolkata')::DATE AS activity_month
    FROM dw.fact_orders fo
    WHERE fo.order_status = 'DELIVERED'
),
cohort_activity AS (
    SELECT
        fos.sla_segment,
        fos.cohort_month,
        (
            (EXTRACT(YEAR FROM cma.activity_month) - EXTRACT(YEAR FROM fos.cohort_month)) * 12
            + (EXTRACT(MONTH FROM cma.activity_month) - EXTRACT(MONTH FROM fos.cohort_month))
        )::INTEGER                                          AS month_number,
        COUNT(DISTINCT cma.customer_sk)                     AS active_customers
    FROM first_order_sla fos
    JOIN customer_monthly_activity cma ON fos.customer_sk = cma.customer_sk
    GROUP BY fos.sla_segment, fos.cohort_month, month_number
),
cohort_sizes AS (
    SELECT
        sla_segment,
        cohort_month,
        COUNT(DISTINCT customer_sk)                         AS cohort_size
    FROM first_order_sla
    GROUP BY sla_segment, cohort_month
)
SELECT
    ca.sla_segment,
    TO_CHAR(ca.cohort_month, 'YYYY-MM')                     AS cohort_month,
    cs.cohort_size,
    ca.month_number,
    ca.active_customers,
    ROUND(100.0 * ca.active_customers / NULLIF(cs.cohort_size, 0), 2) AS retention_pct
FROM cohort_activity ca
JOIN cohort_sizes cs
  ON ca.sla_segment = cs.sla_segment
 AND ca.cohort_month = cs.cohort_month
WHERE ca.month_number BETWEEN 0 AND 6
ORDER BY ca.sla_segment, ca.cohort_month, ca.month_number;
