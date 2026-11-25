"""Unit and integration tests for Net Contribution Margin, Excel simulator, and A/B testing."""

from pathlib import Path

import openpyxl
import pandas as pd

from python.config import PROJECT_ROOT
from python.experiments.ab_testing import required_sample_size_per_arm, two_proportion_z_test
from python.generators.master_data import deterministic_ab_group


def test_ncm_formula_matches_extended_definition():
    proc_orders = PROJECT_ROOT / "data" / "processed" / "fact_orders_clean.csv"
    df = pd.read_csv(proc_orders, nrows=5000)
    expected = (
        df["gross_margin"]
        + df["handling_fee"]
        + df["delivery_fee"]
        + df["surge_fee"]
        - df["discounts"]
        - df["rider_payout"]
        - df["packaging_cost"]
        - df["refund_cost"]
    ).round(2)
    assert (df["net_contribution_margin"] - expected).abs().max() <= 0.02


def test_ab_assignment_is_deterministic_and_balanced():
    g1 = deterministic_ab_group("CUST-000123")
    g2 = deterministic_ab_group("CUST-000123")
    assert g1 == g2
    assert g1 in {"CONTROL", "TREATMENT"}


def test_ab_statistical_helpers():
    n_req = required_sample_size_per_arm(std_dev=40.0, mde=4.5, alpha=0.05, power=0.80)
    assert 1000 <= n_req <= 1500
    z_res = two_proportion_z_test(600, 1000, 650, 1000)
    assert z_res["p_value"] < 0.05
    assert abs(z_res["absolute_diff"] - 0.05) < 1e-6


def test_excel_simulator_structure_and_formulas():
    xlsx_path = PROJECT_ROOT / "excel_models" / "QuickCommerceIQ_Unit_Economics_Simulator.xlsx"
    assert xlsx_path.exists()
    wb = openpyxl.load_workbook(xlsx_path, data_only=False)
    assert wb.sheetnames == ["Inputs", "Unit_Economics", "BreakEven_Model", "Sensitivity_Analysis"]
    ws_ue = wb["Unit_Economics"]
    assert str(ws_ue["B14"].value).startswith("=SUM(")
    ws_be = wb["BreakEven_Model"]
    assert str(ws_be["B8"].value) == "=B6/B7"
    ws_sa = wb["Sensitivity_Analysis"]
    assert str(ws_sa["B5"].value).startswith("=($A5*Inputs!$C$5)")
