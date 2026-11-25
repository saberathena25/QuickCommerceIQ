# QuickCommerceIQ — Metric Definitions & Mathematical Formulas

## 1. Unit Economics (INR ₹)
- **Gross Merchandise Value (GMV):** $\sum \text{cart\_value}$ across placed orders.
- **Product Gross Margin:** $\sum \text{quantity} \times (\text{historical\_unit\_price} - \text{historical\_unit\_cost})$ (realized on `DELIVERED` orders; ₹0 on `CANCELLED`).
- **Net Contribution Margin (Order-Level NCM):**
  $$\text{NCM} = \text{Gross Margin} + \text{Handling Fee} + \text{Delivery Fee} + \text{Surge Fee} - \text{Discounts} - \text{Rider Payout} - \text{Packaging Cost} - \text{Refund Cost}$$
- **Net Store Operating Profit (Fixed-Cost Inclusive):**
  $$\text{Store Operating Profit} = \sum \text{Order NCM} - (\text{Monthly Rent} \times 6 \times 1.15)$$
  where $1.15$ accounts for dark-store electricity, cold-chain power, and utilities.

## 2. Delivery SLA Decomposition (Target: 12.0 Minutes / 720 Seconds)
Evaluated strictly on `DELIVERED` orders:
- **Picking Time:** $\text{packed\_at} - \text{placed\_at}$
- **Assignment & Handover Time:** $\text{dispatched\_at} - \text{packed\_at}$
- **Transit Time:** $\text{delivered\_at} - \text{dispatched\_at}$
- **Total Delivery Time:** $\text{delivered\_at} - \text{placed\_at}$
- **SLA Breach Rate:** $\frac{\text{Count}(\text{Total Delivery Time} > 720\text{s})}{\text{Delivered Orders}} \times 100\%$
- **Primary Bottleneck Classification:** Stage with the largest excess over baseline target (`Picking > 2.5m`, `Assignment > 2.0m`, `Transit > 5.5m`).

## 3. Customer Cohort Retention
- Customers segmented by their **first delivered order** SLA: `FAST (<12m)`, `MEDIUM (12–20m)`, `SLOW (>20m)`.
- **Month $k$ Retention Rate:** $\frac{\text{Unique Customers Active (Delivered) in Cohort Month} + k}{\text{Cohort Size at Month } 0} \times 100\%$.

## 4. Peak-Hour (7 PM–10 PM IST) Stockout Lost GMV
- Non-overlapping interval duration per snapshot via `LEAD(snapshot_timestamp)` capped at `15 minutes` (0.25h) to prevent double-counting.
- Counterfactual in-stock hourly demand rate computed per `(store_id, sku_id, hour_ist, is_weekend)`:
  $$\text{Lost Units} = \frac{\text{In-Stock Units Sold}}{\text{In-Stock Hours}} \times \text{Stockout Hours} \times (1 - 0.25\text{ substitution})$$
- **Estimated Lost GMV:** $\text{Lost Units} \times \text{Historical Selling Price}$
- **Estimated Lost Margin:** $\text{Lost Units} \times \text{Historical Unit Margin}$

## 5. A/B Experiment Primary Metric
- **NPPU (Net Profit per Randomized User, ITT):**
  $$\text{NPPU} = \frac{\sum \text{Net Contribution across all randomized users (including non-converters)}}{\text{Total Randomized Users in Variant}}$$
