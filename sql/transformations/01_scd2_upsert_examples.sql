-- ============================================================================
-- QuickCommerceIQ — Idempotent Upserts & SCD Type 2 Merge Transformations
-- ============================================================================

-- 1. Idempotent Fact Orders Upsert (Prevents duplicate ingestion on replay)
-- Uses ON CONFLICT (order_id) DO UPDATE for late-arriving status corrections.
INSERT INTO dw.fact_orders (
    order_id, customer_sk, store_sk, rider_sk, date_time_sk,
    placed_at, packed_at, dispatched_at, delivered_at, cancelled_at,
    order_status, payment_mode, weather_tag,
    cart_value, discounts, delivery_fee, handling_fee, surge_fee,
    gross_margin, rider_payout, packaging_cost, refund_cost, net_contribution_margin,
    picking_seconds, assignment_seconds, transit_seconds, total_delivery_seconds, is_sla_breach
)
SELECT
    ro.order_id,
    dc.customer_sk,
    ds.store_sk,
    dr.rider_sk,
    TO_CHAR((ro.placed_at::TIMESTAMPTZ AT TIME ZONE 'Asia/Kolkata'), 'YYYYMMDDHH24')::BIGINT,
    ro.placed_at::TIMESTAMPTZ,
    NULLIF(ro.packed_at, '')::TIMESTAMPTZ,
    NULLIF(ro.dispatched_at, '')::TIMESTAMPTZ,
    NULLIF(ro.delivered_at, '')::TIMESTAMPTZ,
    NULLIF(ro.cancelled_at, '')::TIMESTAMPTZ,
    ro.order_status,
    ro.payment_mode,
    ro.weather_tag,
    ro.cart_value::NUMERIC(12, 2),
    ro.discounts::NUMERIC(12, 2),
    ro.delivery_fee::NUMERIC(12, 2),
    ro.handling_fee::NUMERIC(12, 2),
    ro.surge_fee::NUMERIC(12, 2),
    ro.gross_margin::NUMERIC(12, 2),
    ro.rider_payout::NUMERIC(12, 2),
    ro.packaging_cost::NUMERIC(12, 2),
    ro.refund_cost::NUMERIC(12, 2),
    (
        ro.gross_margin::NUMERIC + ro.handling_fee::NUMERIC + ro.delivery_fee::NUMERIC + ro.surge_fee::NUMERIC
        - ro.discounts::NUMERIC - ro.rider_payout::NUMERIC - ro.packaging_cost::NUMERIC - ro.refund_cost::NUMERIC
    )::NUMERIC(12, 2),
    EXTRACT(EPOCH FROM (NULLIF(ro.packed_at, '')::TIMESTAMPTZ - ro.placed_at::TIMESTAMPTZ))::INT,
    EXTRACT(EPOCH FROM (NULLIF(ro.dispatched_at, '')::TIMESTAMPTZ - NULLIF(ro.packed_at, '')::TIMESTAMPTZ))::INT,
    EXTRACT(EPOCH FROM (NULLIF(ro.delivered_at, '')::TIMESTAMPTZ - NULLIF(ro.dispatched_at, '')::TIMESTAMPTZ))::INT,
    EXTRACT(EPOCH FROM (NULLIF(ro.delivered_at, '')::TIMESTAMPTZ - ro.placed_at::TIMESTAMPTZ))::INT,
    (
        ro.order_status = 'DELIVERED'
        AND EXTRACT(EPOCH FROM (NULLIF(ro.delivered_at, '')::TIMESTAMPTZ - ro.placed_at::TIMESTAMPTZ)) > 720
    )
FROM stg.raw_orders ro
JOIN dw.dim_customers dc ON ro.customer_id = dc.customer_id
JOIN dw.dim_dark_stores ds
  ON ro.store_id = ds.store_id
 AND ro.placed_at::TIMESTAMPTZ >= ds.effective_from
 AND (ds.effective_to IS NULL OR ro.placed_at::TIMESTAMPTZ <= ds.effective_to)
LEFT JOIN dw.dim_riders dr ON ro.rider_id = dr.rider_id
WHERE FALSE -- Reference SQL template executed via Python ETL pipeline
ON CONFLICT (order_id) DO UPDATE SET
    order_status = EXCLUDED.order_status,
    refund_cost = EXCLUDED.refund_cost,
    net_contribution_margin = EXCLUDED.net_contribution_margin;
