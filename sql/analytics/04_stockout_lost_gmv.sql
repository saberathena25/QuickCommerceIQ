-- ============================================================================
-- QuickCommerceIQ — Peak-Hour (7 PM - 10 PM IST) Stockout Lost GMV
-- Uses non-overlapping LEAD() snapshot durations and counterfactual in-stock
-- comparable weekday demand rate (adjusted for 75% net lost-demand capture).
-- ============================================================================

WITH snapshot_intervals AS (
    SELECT
        fis.store_sk,
        fis.sku_sk,
        fis.snapshot_timestamp AT TIME ZONE 'Asia/Kolkata'   AS ts_ist,
        EXTRACT(HOUR FROM (fis.snapshot_timestamp AT TIME ZONE 'Asia/Kolkata'))::INT AS hour_ist,
        CASE WHEN EXTRACT(DOW FROM (fis.snapshot_timestamp AT TIME ZONE 'Asia/Kolkata')) IN (0, 6)
             THEN 1 ELSE 0 END                              AS is_weekend,
        fis.is_stockout,
        -- Duration capped at 15 minutes to prevent over-counting across off-peak gaps
        LEAST(
            15.0 / 60.0,
            COALESCE(
                EXTRACT(EPOCH FROM (
                    LEAD(fis.snapshot_timestamp) OVER (
                        PARTITION BY fis.store_sk, fis.sku_sk
                        ORDER BY fis.snapshot_timestamp
                    ) - fis.snapshot_timestamp
                )) / 3600.0,
                15.0 / 60.0
            )
        )                                                   AS interval_hours
    FROM dw.fact_inventory_snapshots fis
),
peak_stockout_hours AS (
    SELECT
        ds.store_id,
        sk.sku_id,
        si.hour_ist,
        si.is_weekend,
        SUM(CASE WHEN si.is_stockout THEN si.interval_hours ELSE 0 END)     AS stockout_hours,
        SUM(CASE WHEN NOT si.is_stockout THEN si.interval_hours ELSE 0 END) AS in_stock_hours
    FROM snapshot_intervals si
    JOIN dw.dim_dark_stores ds ON si.store_sk = ds.store_sk
    JOIN dw.dim_skus sk ON si.sku_sk = sk.sku_sk
    WHERE si.hour_ist IN (19, 20, 21)
    GROUP BY ds.store_id, sk.sku_id, si.hour_ist, si.is_weekend
),
peak_demand AS (
    SELECT
        ds.store_id,
        sk.sku_id,
        dt.hour_ist,
        CASE WHEN dt.is_weekend THEN 1 ELSE 0 END           AS is_weekend,
        SUM(foi.quantity)                                   AS units_sold,
        AVG(foi.historical_unit_price)                      AS avg_selling_price,
        AVG(foi.historical_unit_price - foi.historical_unit_cost) AS avg_unit_margin
    FROM dw.fact_order_items foi
    JOIN dw.fact_orders fo ON foi.order_sk = fo.order_sk
    JOIN dw.dim_dark_stores ds ON fo.store_sk = ds.store_sk
    JOIN dw.dim_skus sk ON foi.sku_sk = sk.sku_sk
    JOIN dw.dim_date_time dt ON fo.date_time_sk = dt.date_time_sk
    WHERE fo.order_status = 'DELIVERED'
      AND dt.hour_ist IN (19, 20, 21)
    GROUP BY ds.store_id, sk.sku_id, dt.hour_ist, dt.is_weekend
)
SELECT
    psh.store_id,
    psh.sku_id,
    psh.hour_ist,
    ROUND(SUM(psh.stockout_hours)::NUMERIC, 2)              AS stockout_hours,
    ROUND(SUM(
        (COALESCE(pd.units_sold, 0) / NULLIF(psh.in_stock_hours, 0))
        * psh.stockout_hours
        * 0.75 -- 25% substitution adjustment
    )::NUMERIC, 2)                                          AS estimated_lost_units,
    ROUND(SUM(
        (COALESCE(pd.units_sold, 0) / NULLIF(psh.in_stock_hours, 0))
        * psh.stockout_hours
        * 0.75
        * COALESCE(pd.avg_selling_price, 0)
    )::NUMERIC, 2)                                          AS estimated_lost_gmv_inr,
    ROUND(SUM(
        (COALESCE(pd.units_sold, 0) / NULLIF(psh.in_stock_hours, 0))
        * psh.stockout_hours
        * 0.75
        * COALESCE(pd.avg_unit_margin, 0)
    )::NUMERIC, 2)                                          AS estimated_lost_margin_inr
FROM peak_stockout_hours psh
LEFT JOIN peak_demand pd
  ON psh.store_id = pd.store_id
 AND psh.sku_id = pd.sku_id
 AND psh.hour_ist = pd.hour_ist
 AND psh.is_weekend = pd.is_weekend
GROUP BY psh.store_id, psh.sku_id, psh.hour_ist
HAVING SUM(psh.stockout_hours) > 0
ORDER BY estimated_lost_gmv_inr DESC;
