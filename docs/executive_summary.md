# QuickCommerceIQ — Executive Summary (Observed Synthetic Results)

> All metrics below are directly calculated from the executed ETL warehouse (`174,288` accepted orders; `167,485` delivered orders) and saved in [analytics_summary.json](../reports/analytics_summary.json) and [ab_experiment_report.json](../reports/ab_experiment_report.json).

## Key Findings

1. **Profitability Deterioration (+₹19.48 → -₹3.27 / Order):**
   - Total 6-month GMV reached **₹4.65 Crore** (`₹46,493,962.99`), with **₹11.18 Lakhs** (`₹1,118,302.84`) total order-level NCM (**₹6.42/order** average).
   - Monthly NCM compressed from **+₹19.48/order (May 2026)** to **-₹3.27/order (October 2026)** due to rising promotional discount burn, higher rider payouts, and SLA-linked refunds.
   - **4 stores** lose money at the order-contribution level (`STR-005 Whitefield Hub -₹6.89`, `STR-016 Saket Hub -₹6.66`, `STR-003 JP Nagar Hub -₹2.36`, `STR-013 Powai Hub -₹1.71`), and **all 25 stores** are net-negative over the 6-month window after fixed rent & utilities.

2. **Delivery SLA & Bottleneck Decomposition (49.86% Breach Rate):**
   - Mean delivery time is **12.47 min** (Median **12.00m**, P90 **18.25m**, P95 **20.27m**): **3.28m picking + 2.81m rider assignment + 6.38m transit**.
   - **9 PM IST (21:00–21:59)** is the worst hour with **75.16% SLA breaches**.
   - **Heavy Rain** pushes SLA breaches from **36.42% (Normal)** to **98.46%**, inflating rider payouts and compressing order margin.

3. **Peak-Hour (7–10 PM) Stockout Lost GMV:**
   - Across 16 tracked high-velocity hero SKUs, **17,469.50 peak stockout hours** resulted in **813.06 estimated lost units**, **₹64,450.87 estimated lost GMV**, and **₹15,545.82 lost contribution margin** (after 25% substitution adjustment and non-overlapping interval capping).

4. **A/B Test Readout (₹199 Control vs ₹249 Treatment):**
   - **SRM Check:** Passed (`χ² = 1.4175`, `p = 0.2338`; `21,122` vs `20,878` users).
   - **NPPU Lift:** **+₹5.72/user** (`-₹4.87` Control → `+₹0.85` Treatment, Welch `p < 0.0001`, Bootstrap 95% CI `[+₹4.98, +₹6.49]`).
   - **AOV Lift:** **+₹8.26** (`₹265.04` → `₹273.30`, `p < 0.0001`).
   - **Guardrail Breach:** 30-Day Repeat Rate declined **-1.97 pp** (`61.34%` → `59.37%`, `p = 0.0047`), breaching the `-1.50 pp` non-inferiority floor.
   - **Decision:** **`TARGETED_ROLLOUT_OR_229_TEST`** — avoid blanket ₹249 rollout; test an intermediate ₹229 threshold or restrict ₹249 to high-density urban hubs.

See [executive_memo.pdf](../reports/executive_memo.pdf) for full charts and store-level tables.
