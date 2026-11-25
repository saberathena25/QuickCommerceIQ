# QuickCommerceIQ — Power BI DAX Measures Library

All measures assume the Star Schema relationships between `vw_fact_orders_enriched` (or `fact_orders`), `dim_dark_stores`, `dim_customers`, `dim_skus`, `dim_date_time`, and pre-computed analytical tables (`analytics_stockout_store_sku_hour`, `analytics_cohort_retention_matrix`, `experiment_results`).

---

## 1. Executive & Unit Economics Measures (INR ₹)

```dax
Total Orders =
COUNTROWS(fact_orders)

Delivered Orders =
CALCULATE(
    COUNTROWS(fact_orders),
    fact_orders[order_status] = "DELIVERED"
)

Total GMV (INR) =
SUM(fact_orders[cart_value])

Total Gross Margin (INR) =
SUM(fact_orders[gross_margin])

Total NCM (INR) =
SUM(fact_orders[net_contribution_margin])

NCM per Order (INR) =
DIVIDE([Total NCM (INR)], [Total Orders], 0)

Gross Margin % =
DIVIDE([Total Gross Margin (INR)], [Total GMV (INR)], 0)

Avg Order Value (AOV) =
DIVIDE([Total GMV (INR)], [Total Orders], 0)

Avg Discount per Order =
AVERAGE(fact_orders[discounts])

Avg Rider Payout per Order =
AVERAGE(fact_orders[rider_payout])

Avg Refund Cost per Order =
AVERAGE(fact_orders[refund_cost])

Estimated 6M Store Fixed Cost (INR) =
SUMX(
    VALUES(dim_dark_stores[store_id]),
    CALCULATE(MAX(dim_dark_stores[monthly_rent])) * 6 * 1.15
)

Net Store Operating Profit (INR) =
[Total NCM (INR)] - [Estimated 6M Store Fixed Cost (INR)]

NCM Color Indicator =
IF([NCM per Order (INR)] >= 0, "#166534", "#991B1B")
```

---

## 2. Delivery SLA & Operational Bottleneck Measures (12-Min Target)

```dax
Average Delivery Time (Min) =
CALCULATE(
    AVERAGE(fact_orders[total_delivery_minutes]),
    fact_orders[order_status] = "DELIVERED"
)

Median Delivery Time (Min) =
CALCULATE(
    MEDIAN(fact_orders[total_delivery_minutes]),
    fact_orders[order_status] = "DELIVERED"
)

P90 Delivery Time (Min) =
CALCULATE(
    PERCENTILEX.INC(fact_orders, fact_orders[total_delivery_minutes], 0.90),
    fact_orders[order_status] = "DELIVERED"
)

SLA Breach Count =
CALCULATE(
    COUNTROWS(fact_orders),
    fact_orders[order_status] = "DELIVERED",
    fact_orders[is_sla_breach] = TRUE()
)

SLA Breach Rate % =
DIVIDE([SLA Breach Count], [Delivered Orders], 0)

Avg Picking Time (Min) =
CALCULATE(
    AVERAGE(fact_orders[picking_minutes]),
    fact_orders[order_status] = "DELIVERED"
)

Avg Rider Assignment Time (Min) =
CALCULATE(
    AVERAGE(fact_orders[assignment_minutes]),
    fact_orders[order_status] = "DELIVERED"
)

Avg Transit Time (Min) =
CALCULATE(
    AVERAGE(fact_orders[transit_minutes]),
    fact_orders[order_status] = "DELIVERED"
)

Primary Operational Bottleneck =
VAR PickExcess = [Avg Picking Time (Min)] - 2.5
VAR AssignExcess = [Avg Rider Assignment Time (Min)] - 2.0
VAR TransitExcess = [Avg Transit Time (Min)] - 5.5
RETURN
SWITCH(
    TRUE(),
    PickExcess >= AssignExcess && PickExcess >= TransitExcess, "PICKING",
    AssignExcess >= PickExcess && AssignExcess >= TransitExcess, "RIDER_ASSIGNMENT",
    "TRANSIT"
)
```

---

## 3. Peak-Hour Stockout Lost GMV Measures (7 PM – 10 PM)

```dax
Estimated Lost GMV (INR) =
SUM(analytics_stockout_store_sku_hour[estimated_lost_gmv_inr])

Estimated Lost Margin (INR) =
SUM(analytics_stockout_store_sku_hour[estimated_lost_margin_inr])

Total Peak Stockout Hours =
SUM(analytics_stockout_store_sku_hour[stockout_hours])
```

---

## 4. Customer Cohort Retention & A/B Experiment Measures

```dax
Cohort Retention % =
DIVIDE(
    SUM(analytics_cohort_retention_matrix[active_customers]),
    SUM(analytics_cohort_retention_matrix[cohort_size]),
    0
)

AB Randomized Users =
COUNTROWS(vw_ab_experiment_itt)

AB NPPU (INR) =
DIVIDE(
    SUM(vw_ab_experiment_itt[itt_net_contribution_inr]),
    [AB Randomized Users],
    0
)

AB Conversion Rate % =
DIVIDE(
    CALCULATE(COUNTROWS(vw_ab_experiment_itt), vw_ab_experiment_itt[completed_orders] > 0),
    [AB Randomized Users],
    0
)
```
