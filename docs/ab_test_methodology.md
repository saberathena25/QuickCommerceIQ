# QuickCommerceIQ — A/B Experimentation Methodology

## Experiment Design
- **Hypothesis:** Increasing the free-delivery basket threshold from **₹199 (Control)** to **₹249 (Treatment)** increases Net Profit per Randomized User (NPPU) via delivery-fee capture and basket top-ups without harming customer repeat behavior.
- **Randomization Unit:** Customer (`42,000` registered users across 25 stores).
- **Assignment:** Deterministic SHA-256 hash (`python/generators/master_data.py::deterministic_ab_group`) persisting 50/50 allocation in `dw.ab_experiment_assignments`.
- **Analysis Principle:** **Intention-to-Treat (ITT)** over the 61-day window (`2026-09-01` to `2026-10-31` IST), retaining all randomized non-converters at `₹0` contribution.

## Power & Hypothesis Testing Suite
- **Parameters:** $\alpha = 0.05$ (two-sided), Power $= 80\%$, MDE $= ₹4.50$ NPPU/user.
- **Required Sample Size:** `1,133` users per arm (actual arms: `21,122` Control, `20,878` Treatment — well-powered).
- **Checks Executed (`python/experiments/ab_testing.py`):**
  1. **SRM Check:** Chi-Square goodness-of-fit against 50/50 split (`p >= 0.001` required).
  2. **NPPU (Primary):** Welch's two-sample t-test + Mann-Whitney U + 2,000-resample Bootstrap 95% CI.
  3. **Conversion Rate, Cart Abandonment, 30-Day Repeat Rate:** Two-proportion Z-test with 95% Wald CIs.
  4. **AOV & Orders/Customer:** Welch's t-test (+ Mann-Whitney U for skewed AOV).
  5. **Guardrail Criteria:** Cart abandonment increase $\le +3.5\text{ pp}$ and 30-day repeat rate 95% CI lower bound $\ge -1.5\text{ pp}$.
