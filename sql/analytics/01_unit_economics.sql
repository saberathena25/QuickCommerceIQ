-- ============================================================================
-- QuickCommerceIQ — Unit Economics & Net Contribution Margin (PostgreSQL)
-- Formula:
--   NCM = Gross Margin + Handling Fees + Delivery Fees + Surge Fees
--         - Discounts - Rider Payout - Packaging Cost - Refund Cost
-- Note: Order-level NCM excludes store fixed costs (rent & utilities).
-- ============================================================================

-- 1. Network Summary & Monthly Trend (6 Months)
SELECT
    dt.year_month,
    COUNT(*)                                                AS total_orders,
    COUNT(*) FILTER (WHERE fo.order_status = 'DELIVERED')   AS delivered_orders,
    ROUND(SUM(fo.cart_value), 2)                            AS total_gmv_inr,
    ROUND(SUM(fo.net_contribution_margin), 2)               AS total_ncm_inr,
    ROUND(AVG(fo.net_contribution_margin), 2)               AS avg_ncm_per_order_inr,
    ROUND(AVG(fo.cart_value), 2)                            AS avg_cart_value_inr,
    ROUND(AVG(fo.discounts), 2)                             AS avg_discount_inr,
    ROUND(AVG(fo.rider_payout), 2)                          AS avg_rider_payout_inr,
    ROUND(AVG(fo.refund_cost), 2)                           AS avg_refund_inr
FROM dw.fact_orders fo
JOIN dw.dim_date_time dt ON fo.date_time_sk = dt.date_time_sk
GROUP BY dt.year_month
ORDER BY dt.year_month;

-- 2. Store-Level Unit Economics vs Fixed-Cost Store Profitability (Bottom 10 Bleeding Stores)
WITH store_orders AS (
    SELECT
        ds.store_id,
        ds.store_name,
        ds.city,
        ds.zone,
        MAX(ds.monthly_rent)                                AS current_monthly_rent_inr,
        COUNT(*)                                            AS total_orders,
        ROUND(SUM(fo.cart_value), 2)                        AS total_gmv_inr,
        ROUND(SUM(fo.net_contribution_margin), 2)           AS order_level_ncm_inr,
        ROUND(AVG(fo.net_contribution_margin), 2)           AS avg_ncm_per_order_inr
    FROM dw.fact_orders fo
    JOIN dw.dim_dark_stores ds ON fo.store_sk = ds.store_sk
    GROUP BY ds.store_id, ds.store_name, ds.city, ds.zone
)
SELECT
    *,
    ROUND(current_monthly_rent_inr * 6 * 1.15, 2)           AS six_month_fixed_rent_utilities_inr,
    ROUND(order_level_ncm_inr - (current_monthly_rent_inr * 6 * 1.15), 2) AS net_store_operating_profit_inr
FROM store_orders
ORDER BY avg_ncm_per_order_inr ASC
LIMIT 10;

-- 3. NCM by City, Weather, Payment Mode, and Hour (IST)
SELECT
    ds.city,
    COUNT(*)                                                AS orders,
    ROUND(SUM(fo.net_contribution_margin), 2)               AS total_ncm_inr,
    ROUND(AVG(fo.net_contribution_margin), 2)               AS avg_ncm_inr
FROM dw.fact_orders fo
JOIN dw.dim_dark_stores ds ON fo.store_sk = ds.store_sk
GROUP BY ds.city
ORDER BY avg_ncm_inr ASC;

SELECT
    fo.weather_tag,
    COUNT(*)                                                AS orders,
    ROUND(AVG(fo.net_contribution_margin), 2)               AS avg_ncm_inr,
    ROUND(AVG(fo.rider_payout), 2)                          AS avg_rider_payout_inr,
    ROUND(AVG(fo.surge_fee), 2)                             AS avg_surge_fee_inr
FROM dw.fact_orders fo
GROUP BY fo.weather_tag
ORDER BY avg_ncm_inr ASC;

SELECT
    fo.payment_mode,
    COUNT(*)                                                AS orders,
    ROUND(AVG(fo.net_contribution_margin), 2)               AS avg_ncm_inr,
    ROUND(AVG(fo.packaging_cost), 2)                        AS avg_handling_pkg_cost_inr
FROM dw.fact_orders fo
GROUP BY fo.payment_mode;

SELECT
    dt.hour_ist,
    COUNT(*)                                                AS orders,
    ROUND(SUM(fo.net_contribution_margin), 2)               AS total_ncm_inr,
    ROUND(AVG(fo.net_contribution_margin), 2)               AS avg_ncm_inr
FROM dw.fact_orders fo
JOIN dw.dim_date_time dt ON fo.date_time_sk = dt.date_time_sk
GROUP BY dt.hour_ist
ORDER BY dt.hour_ist;
