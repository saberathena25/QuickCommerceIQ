"""Statistical A/B Experimentation Framework: Free Delivery Threshold ₹199 (Control) vs ₹249 (Treatment)."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from python.config import PROJECT_ROOT, get_logger, get_settings
from python.db import get_engine

logger = get_logger(__name__)


def required_sample_size_per_arm(
    std_dev: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> int:
    """Two-sample normal approximation sample size per arm."""
    z_alpha = float(stats.norm.ppf(1.0 - alpha / 2.0))
    z_beta = float(stats.norm.ppf(power))
    n = 2.0 * ((z_alpha + z_beta) ** 2) * (std_dev ** 2) / (mde ** 2)
    return int(math.ceil(n))


def two_proportion_z_test(
    x_ctrl: int,
    n_ctrl: int,
    x_trt: int,
    n_trt: int,
) -> dict[str, float]:
    """Two-sided two-proportion z-test with 95% Wald CI for lift (trt - ctrl)."""
    p_ctrl = x_ctrl / n_ctrl
    p_trt = x_trt / n_trt
    p_pool = (x_ctrl + x_trt) / (n_ctrl + n_trt)
    se_pool = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n_ctrl + 1.0 / n_trt))
    z_stat = (p_trt - p_ctrl) / se_pool if se_pool > 0 else 0.0
    p_val = 2.0 * (1.0 - float(stats.norm.cdf(abs(z_stat))))

    se_unpooled = math.sqrt((p_ctrl * (1.0 - p_ctrl) / n_ctrl) + (p_trt * (1.0 - p_trt) / n_trt))
    ci_low = (p_trt - p_ctrl) - 1.96 * se_unpooled
    ci_high = (p_trt - p_ctrl) + 1.96 * se_unpooled
    return {
        "control_rate": p_ctrl,
        "treatment_rate": p_trt,
        "absolute_diff": p_trt - p_ctrl,
        "relative_lift_pct": ((p_trt - p_ctrl) / p_ctrl * 100.0) if p_ctrl > 0 else 0.0,
        "z_stat": z_stat,
        "p_value": p_val,
        "ci_95_low": ci_low,
        "ci_95_high": ci_high,
    }


def welch_t_with_ci(ctrl: np.ndarray, trt: np.ndarray) -> dict[str, float]:
    """Welch's two-sample t-test with 95% confidence interval for difference in means."""
    m_c = float(np.mean(ctrl))
    m_t = float(np.mean(trt))
    v_c = float(np.var(ctrl, ddof=1))
    v_t = float(np.var(trt, ddof=1))
    se = math.sqrt(v_c / len(ctrl) + v_t / len(trt))
    t_stat, p_val = stats.ttest_ind(trt, ctrl, equal_var=False)
    diff = m_t - m_c
    return {
        "control_mean": m_c,
        "treatment_mean": m_t,
        "absolute_diff": diff,
        "relative_lift_pct": (diff / abs(m_c) * 100.0) if m_c != 0 else 0.0,
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "ci_95_low": diff - 1.96 * se,
        "ci_95_high": diff + 1.96 * se,
    }


def bootstrap_mean_diff_ci(
    ctrl: np.ndarray,
    trt: np.ndarray,
    n_boot: int = 2000,
    seed: int = 42,
) -> tuple[float, float]:
    """Bootstrap 95% CI for difference in means (treatment - control)."""
    rng = np.random.default_rng(seed)
    n_c, n_t = len(ctrl), len(trt)
    diffs = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        c_sample = ctrl[rng.integers(0, n_c, size=n_c)]
        t_sample = trt[rng.integers(0, n_t, size=n_t)]
        diffs[b] = t_sample.mean() - c_sample.mean()
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def run_ab_experiment_analysis() -> dict[str, Any]:
    """Execute full ITT A/B test evaluation from warehouse tables and write reports."""
    settings = get_settings()["analytics"]["ab_experiment"]
    alpha = float(settings["alpha"])
    target_power = float(settings["target_power"])
    mde_nppu = float(settings["mde_nppu_inr"])
    max_aband_inc = float(settings["guardrail_cart_abandonment_max_increase"])
    min_rep_diff = float(settings["guardrail_repeat_rate_non_inferiority"])

    engine, backend = get_engine(allow_sqlite_fallback=True)
    p = "dw." if backend == "postgres" else ""

    assign_df = pd.read_sql(
        f"""
        SELECT dc.customer_sk, aa.customer_id, aa.variant, aa.threshold_inr
        FROM {p}ab_experiment_assignments aa
        JOIN {p}dim_customers dc ON aa.customer_id = dc.customer_id
        WHERE aa.experiment_name = '{settings['name']}'
        """,
        engine,
    )

    events_df = pd.read_sql(
        f"""
        SELECT customer_sk, order_sk, variant, event_type, cart_value, net_contribution, event_timestamp
        FROM {p}fact_ab_experiment_events
        WHERE experiment_name = '{settings['name']}'
        """,
        engine,
    )
    events_df["event_dt"] = pd.to_datetime(events_df["event_timestamp"], utc=True)

    # 1. Sample Ratio Mismatch (SRM) Chi-Square check (50/50 expected)
    n_ctrl = int((assign_df["variant"] == "CONTROL").sum())
    n_trt = int((assign_df["variant"] == "TREATMENT").sum())
    n_total = n_ctrl + n_trt
    chi2_srm, p_srm = stats.chisquare(f_obs=[n_ctrl, n_trt], f_exp=[n_total / 2.0, n_total / 2.0])
    srm_passed = bool(p_srm >= 0.001)

    # 2. Build User-Level Intention-to-Treat (ITT) table across ALL 42,000 randomized users
    completed = events_df[events_df["event_type"] == "ORDER_COMPLETED"].copy()
    user_orders = (
        completed.groupby("customer_sk", as_index=False)
        .agg(
            delivered_orders=("order_sk", "count"),
            total_ncm=("net_contribution", "sum"),
            total_gmv=("cart_value", "sum"),
        )
    )
    # Include cancelled order net contribution (e.g. partial rider payout cost) in ITT total contribution
    all_ord_events = events_df[events_df["event_type"].isin(["ORDER_COMPLETED", "ORDER_CANCELLED"])].copy()
    user_itt_ncm = all_ord_events.groupby("customer_sk", as_index=False).agg(itt_net_contribution=("net_contribution", "sum"))

    itt_df = (
        assign_df.merge(user_orders, on="customer_sk", how="left")
        .merge(user_itt_ncm, on="customer_sk", how="left")
    )
    itt_df["delivered_orders"] = itt_df["delivered_orders"].fillna(0).astype(int)
    itt_df["total_ncm"] = itt_df["total_ncm"].fillna(0.0)
    itt_df["itt_net_contribution"] = itt_df["itt_net_contribution"].fillna(0.0)
    itt_df["converted"] = (itt_df["delivered_orders"] > 0).astype(int)

    ctrl_itt = itt_df[itt_df["variant"] == "CONTROL"]
    trt_itt = itt_df[itt_df["variant"] == "TREATMENT"]

    # Power / Sample Size Check
    pooled_std_nppu = float(itt_df["itt_net_contribution"].std(ddof=1))
    req_n_per_arm = required_sample_size_per_arm(pooled_std_nppu, mde_nppu, alpha=alpha, power=target_power)

    # Primary Metric: NPPU (Welch's t-test + Mann-Whitney U + Bootstrap CI)
    nppu_welch = welch_t_with_ci(ctrl_itt["itt_net_contribution"].to_numpy(), trt_itt["itt_net_contribution"].to_numpy())
    u_nppu, p_mw_nppu = stats.mannwhitneyu(
        trt_itt["itt_net_contribution"].to_numpy(),
        ctrl_itt["itt_net_contribution"].to_numpy(),
        alternative="two-sided",
    )
    boot_low, boot_high = bootstrap_mean_diff_ci(
        ctrl_itt["itt_net_contribution"].to_numpy(),
        trt_itt["itt_net_contribution"].to_numpy(),
        n_boot=2000,
        seed=42,
    )

    # Secondary 1: Conversion Rate
    conv_test = two_proportion_z_test(
        int(ctrl_itt["converted"].sum()), len(ctrl_itt),
        int(trt_itt["converted"].sum()), len(trt_itt),
    )

    # Secondary 2: Average Order Value (order-level among delivered orders)
    ctrl_aov_vals = completed.loc[completed["variant"] == "CONTROL", "cart_value"].to_numpy()
    trt_aov_vals = completed.loc[completed["variant"] == "TREATMENT", "cart_value"].to_numpy()
    aov_welch = welch_t_with_ci(ctrl_aov_vals, trt_aov_vals)
    _, p_mw_aov = stats.mannwhitneyu(trt_aov_vals, ctrl_aov_vals, alternative="two-sided")

    # Secondary 3: Orders per Randomized Customer
    ord_per_cust_welch = welch_t_with_ci(
        ctrl_itt["delivered_orders"].to_numpy(dtype=float),
        trt_itt["delivered_orders"].to_numpy(dtype=float),
    )

    # Guardrail 1: Cart Abandonment Rate
    n_aband_ctrl = int(((events_df["variant"] == "CONTROL") & (events_df["event_type"] == "CART_ABANDONED")).sum())
    n_tot_cart_ctrl = int((events_df["variant"] == "CONTROL").sum())
    n_aband_trt = int(((events_df["variant"] == "TREATMENT") & (events_df["event_type"] == "CART_ABANDONED")).sum())
    n_tot_cart_trt = int((events_df["variant"] == "TREATMENT").sum())
    aband_test = two_proportion_z_test(n_aband_ctrl, n_tot_cart_ctrl, n_aband_trt, n_tot_cart_trt)

    # Guardrail 2: 30-Day Repeat Rate (Sep 1-30 converters who ordered again within 30 days)
    sep_cutoff = pd.Timestamp("2026-10-01T00:00:00Z")
    first_exp = completed.sort_values("event_dt").drop_duplicates("customer_sk", keep="first")
    sep_converters = first_exp[first_exp["event_dt"] < sep_cutoff][["customer_sk", "variant", "event_dt"]].rename(columns={"event_dt": "first_dt"})
    subseq = completed.merge(sep_converters, on=["customer_sk", "variant"], how="inner")
    subseq["days_since_first"] = (subseq["event_dt"] - subseq["first_dt"]).dt.total_seconds() / 86400.0
    repeat_30d_cust = set(subseq[(subseq["days_since_first"] > 0) & (subseq["days_since_first"] <= 30.0)]["customer_sk"])
    sep_converters["repeated_30d"] = sep_converters["customer_sk"].isin(repeat_30d_cust).astype(int)

    rep_ctrl = sep_converters[sep_converters["variant"] == "CONTROL"]
    rep_trt = sep_converters[sep_converters["variant"] == "TREATMENT"]
    repeat_test = two_proportion_z_test(
        int(rep_ctrl["repeated_30d"].sum()), len(rep_ctrl),
        int(rep_trt["repeated_30d"].sum()), len(rep_trt),
    )

    # Evaluate Guardrails & Final Recommendation
    nppu_sig_positive = (nppu_welch["p_value"] < alpha) and (nppu_welch["absolute_diff"] > 0)
    guardrail_aband_ok = aband_test["absolute_diff"] <= max_aband_inc
    guardrail_repeat_ok = repeat_test["ci_95_low"] >= min_rep_diff

    if not srm_passed:
        recommendation = "INVALID_SRM_INVESTIGATE"
        rationale = "Sample Ratio Mismatch detected; experiment randomization integrity compromised."
    elif nppu_sig_positive and guardrail_aband_ok and guardrail_repeat_ok:
        recommendation = "ROLL_OUT_249_THRESHOLD"
        rationale = (
            f"Treatment (₹249 threshold) delivers statistically significant NPPU lift of "
            f"+₹{nppu_welch['absolute_diff']:.2f}/user (p={nppu_welch['p_value']:.4f}) "
            f"with cart abandonment and 30-day repeat guardrails within acceptable bounds."
        )
    elif nppu_sig_positive and (not guardrail_aband_ok or not guardrail_repeat_ok):
        recommendation = "TARGETED_ROLLOUT_OR_229_TEST"
        rationale = (
            f"Treatment increased NPPU by +₹{nppu_welch['absolute_diff']:.2f}/user (p={nppu_welch['p_value']:.4f}) "
            f"and AOV by +₹{aov_welch['absolute_diff']:.2f}, but breached a guardrail "
            f"(cart abandonment +{aband_test['absolute_diff']*100:.2f}pp, repeat diff {repeat_test['absolute_diff']*100:.2f}pp). "
            f"Test an intermediate ₹229 threshold or restrict ₹249 to high-density metro stores."
        )
    else:
        recommendation = "DO_NOT_SHIP_KEEP_199"
        rationale = (
            f"Treatment did not achieve statistically significant positive NPPU lift "
            f"(diff=₹{nppu_welch['absolute_diff']:.2f}, p={nppu_welch['p_value']:.4f}). Keep ₹199 threshold."
        )

    results_rows = [
        {
            "metric": "NPPU (Net Profit per Randomized User, ₹)",
            "role": "PRIMARY",
            "control_value": round(nppu_welch["control_mean"], 4),
            "treatment_value": round(nppu_welch["treatment_mean"], 4),
            "absolute_diff": round(nppu_welch["absolute_diff"], 4),
            "relative_lift_pct": round(nppu_welch["relative_lift_pct"], 2),
            "test_used": "Welch t-test + Mann-Whitney U + Bootstrap",
            "statistic": round(nppu_welch["t_stat"], 4),
            "p_value": round(nppu_welch["p_value"], 6),
            "mann_whitney_p": round(float(p_mw_nppu), 6),
            "ci_95_low": round(nppu_welch["ci_95_low"], 4),
            "ci_95_high": round(nppu_welch["ci_95_high"], 4),
            "bootstrap_95_low": round(boot_low, 4),
            "bootstrap_95_high": round(boot_high, 4),
            "significant_at_5pct": nppu_welch["p_value"] < alpha,
        },
        {
            "metric": "Conversion Rate (ITT)",
            "role": "SECONDARY",
            "control_value": round(conv_test["control_rate"], 4),
            "treatment_value": round(conv_test["treatment_rate"], 4),
            "absolute_diff": round(conv_test["absolute_diff"], 4),
            "relative_lift_pct": round(conv_test["relative_lift_pct"], 2),
            "test_used": "Two-Proportion Z-Test",
            "statistic": round(conv_test["z_stat"], 4),
            "p_value": round(conv_test["p_value"], 6),
            "mann_whitney_p": None,
            "ci_95_low": round(conv_test["ci_95_low"], 4),
            "ci_95_high": round(conv_test["ci_95_high"], 4),
            "bootstrap_95_low": None,
            "bootstrap_95_high": None,
            "significant_at_5pct": conv_test["p_value"] < alpha,
        },
        {
            "metric": "AOV (Average Order Value, ₹)",
            "role": "SECONDARY",
            "control_value": round(aov_welch["control_mean"], 2),
            "treatment_value": round(aov_welch["treatment_mean"], 2),
            "absolute_diff": round(aov_welch["absolute_diff"], 2),
            "relative_lift_pct": round(aov_welch["relative_lift_pct"], 2),
            "test_used": "Welch t-test + Mann-Whitney U",
            "statistic": round(aov_welch["t_stat"], 4),
            "p_value": round(aov_welch["p_value"], 6),
            "mann_whitney_p": round(float(p_mw_aov), 6),
            "ci_95_low": round(aov_welch["ci_95_low"], 2),
            "ci_95_high": round(aov_welch["ci_95_high"], 2),
            "bootstrap_95_low": None,
            "bootstrap_95_high": None,
            "significant_at_5pct": aov_welch["p_value"] < alpha,
        },
        {
            "metric": "Orders per Randomized Customer",
            "role": "SECONDARY",
            "control_value": round(ord_per_cust_welch["control_mean"], 4),
            "treatment_value": round(ord_per_cust_welch["treatment_mean"], 4),
            "absolute_diff": round(ord_per_cust_welch["absolute_diff"], 4),
            "relative_lift_pct": round(ord_per_cust_welch["relative_lift_pct"], 2),
            "test_used": "Welch t-test",
            "statistic": round(ord_per_cust_welch["t_stat"], 4),
            "p_value": round(ord_per_cust_welch["p_value"], 6),
            "mann_whitney_p": None,
            "ci_95_low": round(ord_per_cust_welch["ci_95_low"], 4),
            "ci_95_high": round(ord_per_cust_welch["ci_95_high"], 4),
            "bootstrap_95_low": None,
            "bootstrap_95_high": None,
            "significant_at_5pct": ord_per_cust_welch["p_value"] < alpha,
        },
        {
            "metric": "Cart Abandonment Rate",
            "role": "GUARDRAIL",
            "control_value": round(aband_test["control_rate"], 4),
            "treatment_value": round(aband_test["treatment_rate"], 4),
            "absolute_diff": round(aband_test["absolute_diff"], 4),
            "relative_lift_pct": round(aband_test["relative_lift_pct"], 2),
            "test_used": "Two-Proportion Z-Test",
            "statistic": round(aband_test["z_stat"], 4),
            "p_value": round(aband_test["p_value"], 6),
            "mann_whitney_p": None,
            "ci_95_low": round(aband_test["ci_95_low"], 4),
            "ci_95_high": round(aband_test["ci_95_high"], 4),
            "bootstrap_95_low": None,
            "bootstrap_95_high": None,
            "significant_at_5pct": aband_test["p_value"] < alpha,
        },
        {
            "metric": "30-Day Repeat Rate",
            "role": "GUARDRAIL",
            "control_value": round(repeat_test["control_rate"], 4),
            "treatment_value": round(repeat_test["treatment_rate"], 4),
            "absolute_diff": round(repeat_test["absolute_diff"], 4),
            "relative_lift_pct": round(repeat_test["relative_lift_pct"], 2),
            "test_used": "Two-Proportion Z-Test",
            "statistic": round(repeat_test["z_stat"], 4),
            "p_value": round(repeat_test["p_value"], 6),
            "mann_whitney_p": None,
            "ci_95_low": round(repeat_test["ci_95_low"], 4),
            "ci_95_high": round(repeat_test["ci_95_high"], 4),
            "bootstrap_95_low": None,
            "bootstrap_95_high": None,
            "significant_at_5pct": repeat_test["p_value"] < alpha,
        },
    ]

    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    results_df = pd.DataFrame(results_rows)
    results_df.to_csv(reports_dir / "experiment_results.csv", index=False)

    summary = {
        "experiment_name": settings["name"],
        "control_threshold_inr": settings["control_threshold_inr"],
        "treatment_threshold_inr": settings["treatment_threshold_inr"],
        "sample_size": {
            "control_users": n_ctrl,
            "treatment_users": n_trt,
            "total_randomized_users": n_total,
            "required_per_arm_for_80pct_power": req_n_per_arm,
            "adequately_powered": bool(min(n_ctrl, n_trt) >= req_n_per_arm),
        },
        "srm_check": {
            "chi_square": round(float(chi2_srm), 4),
            "p_value": round(float(p_srm), 6),
            "srm_passed": srm_passed,
        },
        "guardrails": {
            "cart_abandonment_within_limit": bool(guardrail_aband_ok),
            "repeat_rate_non_inferior": bool(guardrail_repeat_ok),
        },
        "recommendation": recommendation,
        "rationale": rationale,
        "metrics": results_rows,
    }
    with (reports_dir / "ab_experiment_report.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    logger.info("A/B Experiment analysis complete. Recommendation: %s", recommendation)
    return summary


if __name__ == "__main__":
    out = run_ab_experiment_analysis()
    print(json.dumps(out, indent=2))
