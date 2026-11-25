"""Generate QuickCommerceIQ_Unit_Economics_Simulator.xlsx using openpyxl with live Excel formulas."""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from python.config import PROJECT_ROOT, get_logger

logger = get_logger(__name__)

INR_FMT = '"₹"#,##,##0.00;-"₹"#,##,##0.00;"₹"0.00'
INR_INT_FMT = '"₹"#,##,##0;-"₹"#,##,##0;"₹"0'
PCT_FMT = "0.0%"

NAVY_FILL = PatternFill("solid", fgColor="1B2A4A")
SLATE_FILL = PatternFill("solid", fgColor="2F4858")
SUBHDR_FILL = PatternFill("solid", fgColor="E8EEF5")
INPUT_FILL = PatternFill("solid", fgColor="FFF9E6")
GREEN_FILL = PatternFill("solid", fgColor="D9F2E6")
RED_FILL = PatternFill("solid", fgColor="FADBD8")
ZEBRA_FILL = PatternFill("solid", fgColor="F7F9FC")

FONT_TITLE = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
FONT_HDR = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
FONT_SUBHDR = Font(name="Calibri", size=11, bold=True, color="1B2A4A")
FONT_BODY = Font(name="Calibri", size=10, color="1F2937")
FONT_BOLD = Font(name="Calibri", size=10, bold=True, color="1F2937")
FONT_INPUT = Font(name="Calibri", size=10, bold=True, color="0B5394")

THIN_BORDER = Border(
    left=Side(style="thin", color="CBD5E1"),
    right=Side(style="thin", color="CBD5E1"),
    top=Side(style="thin", color="CBD5E1"),
    bottom=Side(style="thin", color="CBD5E1"),
)


def _style_banner(ws, title: str, max_col: int = 8) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
    cell = ws.cell(row=1, column=1, value=title)
    cell.font = FONT_TITLE
    cell.fill = NAVY_FILL
    cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 30
    ws.views.sheetView[0].showGridLines = True


def _load_baseline_defaults() -> dict[str, float]:
    """Pull actual baseline averages from analytics_summary.json if available, else realistic defaults."""
    defaults = {
        "aov": 265.0,
        "gm_pct": 0.225,
        "handling": 5.0,
        "delivery_fee": 7.50,
        "discounts": 24.50,
        "rider_normal": 31.0,
        "rider_monsoon": 39.5,
        "packaging": 6.80,
        "refund": 3.20,
        "surge": 2.10,
        "threshold": 199.0,
        "monthly_rent_util": 420000.0,
        "monthly_orders_per_store": 6500.0,
    }
    summary_path = PROJECT_ROOT / "reports" / "analytics_summary.json"
    if summary_path.exists():
        try:
            with summary_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            ue = data.get("unit_economics", {})
            if ue.get("total_orders", 0) > 0 and ue.get("total_gmv_inr", 0) > 0:
                defaults["aov"] = round(ue["total_gmv_inr"] / ue["total_orders"], 2)
        except Exception:
            pass
    return defaults


def build_excel_simulator(output_path: Path | None = None) -> Path:
    """Create the 4-sheet QuickCommerceIQ_Unit_Economics_Simulator.xlsx workbook."""
    if output_path is None:
        output_path = PROJECT_ROOT / "excel_models" / "QuickCommerceIQ_Unit_Economics_Simulator.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    d = _load_baseline_defaults()
    wb = openpyxl.Workbook()

    # ========================================================================
    # 1. INPUTS SHEET
    # ========================================================================
    ws_in = wb.active
    ws_in.title = "Inputs"
    _style_banner(ws_in, "QuickCommerceIQ — Unit Economics & Store Financial Simulator (Inputs)", max_col=5)

    headers = ["Parameter", "Variable Code", "Input Value", "Unit / Format", "Business Notes"]
    for col_idx, h in enumerate(headers, start=1):
        c = ws_in.cell(row=3, column=col_idx, value=h)
        c.font = FONT_HDR
        c.fill = SLATE_FILL
        c.alignment = Alignment(horizontal="center" if col_idx in (3, 4) else "left", vertical="center")
        c.border = THIN_BORDER
    ws_in.row_dimensions[3].height = 24

    input_rows = [
        ("Average Order Value (AOV)", "AOV", d["aov"], INR_FMT, "Mean cart value in INR (₹149–₹399 range)"),
        ("Gross Margin Percentage", "GM_PCT", d["gm_pct"], PCT_FMT, "Weighted category gross margin %"),
        ("Handling Revenue per Order", "HANDLING_REV", d["handling"], INR_FMT, "Platform handling fee charged to customer"),
        ("Delivery Fee Revenue per Order", "DELIVERY_REV", d["delivery_fee"], INR_FMT, "Effective realized delivery fee across orders"),
        ("Discount per Order", "DISCOUNT_COST", d["discounts"], INR_FMT, "Promotional & coupon burn per order"),
        ("Normal Weather Rider Payout", "RIDER_NORMAL", d["rider_normal"], INR_FMT, "Base + distance payout in normal weather"),
        ("Monsoon Weather Rider Payout", "RIDER_MONSOON", d["rider_monsoon"], INR_FMT, "Includes monsoon & heavy-rain incentives"),
        ("Packaging Cost per Order", "PACKAGING_COST", d["packaging"], INR_FMT, "Bags, cold-chain pouches & COD handling"),
        ("Refund Cost per Order", "REFUND_COST", d["refund"], INR_FMT, "Expected quality/SLA refund cost per order"),
        ("Surge Revenue per Order", "SURGE_REV", d["surge"], INR_FMT, "Average rain/peak surge fee recovered"),
        ("Free-Delivery Threshold", "THRESHOLD", d["threshold"], INR_INT_FMT, "A/B Test lever: ₹199 (Control) vs ₹249 (Treatment)"),
        ("Active Weather Scenario", "WEATHER_MODE", "NORMAL", "@", "Select NORMAL or MONSOON"),
        ("Monthly Dark Store Fixed Rent + Utilities", "FIXED_COST", d["monthly_rent_util"], INR_INT_FMT, "Store rent + electricity + cold-room utilities"),
        ("Monthly Orders per Dark Store", "STORE_ORDERS", d["monthly_orders_per_store"], "#,##0", "Average monthly order volume per dark store"),
    ]

    for idx, (label, code, val, num_fmt, note) in enumerate(input_rows, start=4):
        ws_in.cell(row=idx, column=1, value=label).font = FONT_BOLD
        ws_in.cell(row=idx, column=2, value=code).font = FONT_BODY
        c_val = ws_in.cell(row=idx, column=3, value=val)
        c_val.font = FONT_INPUT
        c_val.fill = INPUT_FILL
        c_val.number_format = num_fmt
        c_val.alignment = Alignment(horizontal="right", vertical="center")
        ws_in.cell(row=idx, column=4, value="INR / %" if num_fmt != "@" else "Text").font = FONT_BODY
        ws_in.cell(row=idx, column=5, value=note).font = FONT_BODY
        for col_i in range(1, 6):
            ws_in.cell(row=idx, column=col_i).border = THIN_BORDER

    # Excel Data Validations
    dv_pos = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0", allow_blank=False)
    dv_pos.errorTitle = "Invalid Input"
    dv_pos.error = "Financial inputs must be non-negative."
    ws_in.add_data_validation(dv_pos)
    for r in [4, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17]:
        dv_pos.add(f"C{r}")

    dv_pct = DataValidation(type="decimal", operator="between", formula1="0.01", formula2="0.80", allow_blank=False)
    ws_in.add_data_validation(dv_pct)
    dv_pct.add("C5")

    dv_thresh = DataValidation(type="list", formula1='"199,249"', allow_blank=False)
    ws_in.add_data_validation(dv_thresh)
    dv_thresh.add("C14")

    dv_weather = DataValidation(type="list", formula1='"NORMAL,MONSOON"', allow_blank=False)
    ws_in.add_data_validation(dv_weather)
    dv_weather.add("C15")

    # ========================================================================
    # 2. UNIT_ECONOMICS SHEET
    # ========================================================================
    ws_ue = wb.create_sheet("Unit_Economics")
    _style_banner(ws_ue, "QuickCommerceIQ — Order-Level Unit Economics & Threshold Scenarios", max_col=6)

    ue_headers = [
        "Line Item",
        "Active Scenario",
        "Normal Weather",
        "Monsoon Weather",
        "₹199 Threshold (Control)",
        "₹249 Threshold (Treatment)",
    ]
    for c_i, h in enumerate(ue_headers, start=1):
        c = ws_ue.cell(row=3, column=c_i, value=h)
        c.font = FONT_HDR
        c.fill = SLATE_FILL
        c.alignment = Alignment(horizontal="center" if c_i > 1 else "left", vertical="center")
        c.border = THIN_BORDER
    ws_ue.row_dimensions[3].height = 24

    # Rows 4-15: AOV, GM%, GM, Handling, Delivery, Surge, Discounts, Rider Payout, Packaging, Refund, NCM, Fixed Cost/Order, Store Net Profit/Order
    ue_rows = [
        ("Average Order Value (AOV)", "=Inputs!C4", "=Inputs!C4", "=Inputs!C4", "=Inputs!C4", "=Inputs!C4*1.045", INR_FMT),
        ("Gross Margin %", "=Inputs!C5", "=Inputs!C5", "=Inputs!C5", "=Inputs!C5", "=Inputs!C5", PCT_FMT),
        ("Gross Margin (₹)", "=B4*B5", "=C4*C5", "=D4*D5", "=E4*E5", "=F4*F5", INR_FMT),
        ("Handling Revenue (+)", "=Inputs!C6", "=Inputs!C6", "=Inputs!C6", "=Inputs!C6", "=Inputs!C6", INR_FMT),
        ("Delivery Fee Revenue (+)", "=IF(Inputs!C14=249, Inputs!C7*1.48, Inputs!C7)", "=Inputs!C7", "=Inputs!C7", "=Inputs!C7", "=Inputs!C7*1.48", INR_FMT),
        ("Surge Revenue (+)", '=IF(Inputs!C15="MONSOON", Inputs!C13*2.2, Inputs!C13)', "=Inputs!C13*0.4", "=Inputs!C13*2.2", "=Inputs!C13", "=Inputs!C13", INR_FMT),
        ("Discounts (-)", "=-Inputs!C8", "=-Inputs!C8", "=-Inputs!C8", "=-Inputs!C8", "=-Inputs!C8", INR_FMT),
        ("Rider Payout (-)", '=-IF(Inputs!C15="MONSOON", Inputs!C10, Inputs!C9)', "=-Inputs!C9", "=-Inputs!C10", "=-Inputs!C9", "=-Inputs!C9", INR_FMT),
        ("Packaging Cost (-)", "=-Inputs!C11", "=-Inputs!C11", "=-Inputs!C11", "=-Inputs!C11", "=-Inputs!C11", INR_FMT),
        ("Refund Cost (-)", '=-IF(Inputs!C15="MONSOON", Inputs!C12*1.35, Inputs!C12)', "=-Inputs!C12", "=-Inputs!C12*1.35", "=-Inputs!C12", "=-Inputs!C12", INR_FMT),
        ("Net Contribution Margin (NCM / Order)", "=SUM(B6:B13)", "=SUM(C6:C13)", "=SUM(D6:D13)", "=SUM(E6:E13)", "=SUM(F6:F13)", INR_FMT),
        ("Allocated Fixed Store Cost / Order", "=-Inputs!C16/Inputs!C17", "=-Inputs!C16/Inputs!C17", "=-Inputs!C16/Inputs!C17", "=-Inputs!C16/Inputs!C17", "=-Inputs!C16/Inputs!C17", INR_FMT),
        ("Net Store Operating Profit / Order", "=B14+B15", "=C14+C15", "=D14+D15", "=E14+E15", "=F14+F15", INR_FMT),
        ("Monthly Store Operating Profit (₹)", "=B16*Inputs!C17", "=C16*Inputs!C17", "=D16*Inputs!C17", "=E16*Inputs!C17", "=F16*Inputs!C17", INR_INT_FMT),
    ]

    for r_idx, (lbl, f_b, f_c, f_d, f_e, f_f, fmt) in enumerate(ue_rows, start=4):
        is_key = lbl.startswith("Net Contribution") or lbl.startswith("Net Store") or lbl.startswith("Monthly Store")
        c_lbl = ws_ue.cell(row=r_idx, column=1, value=lbl)
        c_lbl.font = FONT_BOLD if is_key else FONT_BODY
        c_lbl.fill = SUBHDR_FILL if is_key else PatternFill(fill_type=None)
        c_lbl.border = THIN_BORDER
        for c_i, formula in enumerate([f_b, f_c, f_d, f_e, f_f], start=2):
            cell = ws_ue.cell(row=r_idx, column=c_i, value=formula)
            cell.font = FONT_BOLD if is_key else FONT_BODY
            cell.fill = SUBHDR_FILL if is_key else PatternFill(fill_type=None)
            cell.number_format = fmt
            cell.alignment = Alignment(horizontal="right", vertical="center")
            cell.border = THIN_BORDER

    ws_ue.conditional_formatting.add(
        "B14:F17",
        CellIsRule(operator="lessThan", formula=["0"], fill=RED_FILL, font=Font(bold=True, color="991B1B")),
    )
    ws_ue.conditional_formatting.add(
        "B14:F17",
        CellIsRule(operator="greaterThanOrEqual", formula=["0"], fill=GREEN_FILL, font=Font(bold=True, color="166534")),
    )

    # ========================================================================
    # 3. BREAKEVEN_MODEL SHEET
    # ========================================================================
    ws_be = wb.create_sheet("BreakEven_Model")
    _style_banner(ws_be, "QuickCommerceIQ — Order Contribution vs Fixed-Cost Store Break-Even Model", max_col=5)

    be_headers = ["Break-Even Metric", "Normal (₹199)", "Normal (₹249)", "Monsoon (₹199)", "Formula / Interpretation"]
    for c_i, h in enumerate(be_headers, start=1):
        c = ws_be.cell(row=3, column=c_i, value=h)
        c.font = FONT_HDR
        c.fill = SLATE_FILL
        c.border = THIN_BORDER
    ws_be.row_dimensions[3].height = 24

    be_rows = [
        ("Variable Cost Burden (Discounts + Rider + Pkg + Refund)", "=Inputs!C8+Inputs!C9+Inputs!C11+Inputs!C12", "=Inputs!C8+Inputs!C9+Inputs!C11+Inputs!C12", "=Inputs!C8+Inputs!C10+Inputs!C11+(Inputs!C12*1.35)", "Total variable deductions per order", INR_FMT),
        ("Non-Product Fee Revenue (Handling + Delivery + Surge)", "=Inputs!C6+Inputs!C7+(Inputs!C13*0.4)", "=Inputs!C6+(Inputs!C7*1.48)+(Inputs!C13*0.4)", "=Inputs!C6+Inputs!C7+(Inputs!C13*2.2)", "Ancillary fee cushion per order", INR_FMT),
        ("Net Variable Deficit to Cover via Gross Margin", "=B4-B5", "=C4-C5", "=D4-D5", "Required Gross Margin ₹ to reach NCM = 0", INR_FMT),
        ("Gross Margin %", "=Inputs!C5", "=Inputs!C5", "=Inputs!C5", "Category margin conversion ratio", PCT_FMT),
        ("Order-Level Contribution Break-Even AOV (₹)", "=B6/B7", "=C6/C7", "=D6/D7", "AOV where Order NCM = ₹0 (excludes rent)", INR_FMT),
        ("Allocated Fixed Store Cost per Order (₹)", "=Inputs!C16/Inputs!C17", "=Inputs!C16/Inputs!C17", "=Inputs!C16/Inputs!C17", "Monthly fixed rent & utilities / store orders", INR_FMT),
        ("Fixed-Cost-Inclusive Store Break-Even AOV (₹)", "=(B6+B9)/B7", "=(C6+C9)/C7", "=(D6+D9)/D7", "AOV where Store Operating Profit = ₹0", INR_FMT),
        ("Current Expected NCM per Order (₹)", "=Unit_Economics!C14", "=Unit_Economics!F14", "=Unit_Economics!D14", "From Unit_Economics tab", INR_FMT),
        ("Store Break-Even Monthly Order Volume", '=IF(B11>0, Inputs!C16/B11, "NEGATIVE_NCM")', '=IF(C11>0, Inputs!C16/C11, "NEGATIVE_NCM")', '=IF(D11>0, Inputs!C16/D11, "NEGATIVE_NCM")', "Orders/month needed to cover store fixed rent", "#,##0"),
    ]

    for r_idx, (lbl, f_b, f_c, f_d, desc, fmt) in enumerate(be_rows, start=4):
        is_key = "Break-Even" in lbl
        ws_be.cell(row=r_idx, column=1, value=lbl).font = FONT_BOLD if is_key else FONT_BODY
        for c_i, val in enumerate([f_b, f_c, f_d], start=2):
            c = ws_be.cell(row=r_idx, column=c_i, value=val)
            c.font = FONT_BOLD if is_key else FONT_BODY
            c.number_format = fmt
            c.alignment = Alignment(horizontal="right", vertical="center")
        ws_be.cell(row=r_idx, column=5, value=desc).font = FONT_BODY
        for c_i in range(1, 6):
            cell = ws_be.cell(row=r_idx, column=c_i)
            cell.border = THIN_BORDER
            if is_key:
                cell.fill = SUBHDR_FILL

    # ========================================================================
    # 4. SENSITIVITY_ANALYSIS SHEET (2-Variable Dynamic Formula Grids)
    # ========================================================================
    ws_sa = wb.create_sheet("Sensitivity_Analysis")
    _style_banner(ws_sa, "QuickCommerceIQ — Two-Variable Sensitivity Analysis: NCM per Order (AOV vs Rider Payout)", max_col=9)

    aov_values = list(range(149, 400, 25))  # 149 to 399 step 25 (11 rows)
    rider_values = list(range(20, 51, 5))   # 20 to 50 step 5 (7 cols)

    def _write_sensitivity_grid(start_row: int, title: str, is_monsoon: bool) -> int:
        ws_sa.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=8)
        t_cell = ws_sa.cell(row=start_row, column=1, value=title)
        t_cell.font = FONT_SUBHDR
        t_cell.fill = SUBHDR_FILL
        t_cell.alignment = Alignment(horizontal="left", vertical="center")

        hdr_row = start_row + 1
        c_corner = ws_sa.cell(row=hdr_row, column=1, value="AOV \\ Rider Payout")
        c_corner.font = FONT_HDR
        c_corner.fill = SLATE_FILL
        c_corner.border = THIN_BORDER
        for c_offset, rp in enumerate(rider_values):
            col_idx = 2 + c_offset
            c = ws_sa.cell(row=hdr_row, column=col_idx, value=rp)
            c.font = FONT_HDR
            c.fill = SLATE_FILL
            c.number_format = INR_INT_FMT
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = THIN_BORDER

        first_data_row = hdr_row + 1
        for r_offset, aov in enumerate(aov_values):
            r_idx = first_data_row + r_offset
            c_aov = ws_sa.cell(row=r_idx, column=1, value=aov)
            c_aov.font = FONT_BOLD
            c_aov.fill = ZEBRA_FILL
            c_aov.number_format = INR_INT_FMT
            c_aov.alignment = Alignment(horizontal="right", vertical="center")
            c_aov.border = THIN_BORDER

            for c_offset in range(len(rider_values)):
                col_idx = 2 + c_offset
                col_ltr = get_column_letter(col_idx)
                surge_expr = "Inputs!$C$13*2.2" if is_monsoon else "Inputs!$C$13*0.4"
                refund_expr = "Inputs!$C$12*1.35" if is_monsoon else "Inputs!$C$12"
                # Dynamic formula incorporating AOV ($A{r_idx}), Rider Payout ({col_ltr}${hdr_row}), and Threshold (Inputs!$C$14)
                formula = (
                    f"=($A{r_idx}*Inputs!$C$5)"
                    f"+Inputs!$C$6"
                    f"+IF($A{r_idx}<Inputs!$C$14,25,0)"
                    f"+{surge_expr}"
                    f"-Inputs!$C$8"
                    f"-{col_ltr}${hdr_row}"
                    f"-Inputs!$C$11"
                    f"-{refund_expr}"
                )
                cell = ws_sa.cell(row=r_idx, column=col_idx, value=formula)
                cell.font = FONT_BODY
                cell.number_format = INR_FMT
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.border = THIN_BORDER

        last_data_row = first_data_row + len(aov_values) - 1
        rng_str = f"B{first_data_row}:H{last_data_row}"
        ws_sa.conditional_formatting.add(
            rng_str,
            CellIsRule(operator="lessThan", formula=["0"], fill=RED_FILL, font=Font(color="991B1B")),
        )
        ws_sa.conditional_formatting.add(
            rng_str,
            CellIsRule(operator="greaterThanOrEqual", formula=["0"], fill=GREEN_FILL, font=Font(color="166534")),
        )
        return last_data_row + 2

    next_r = _write_sensitivity_grid(
        3,
        "1. NORMAL WEATHER — Order NCM (₹) across AOV (₹149–₹399) & Rider Payout (₹20–₹50) [Threshold = Inputs!C14]",
        is_monsoon=False,
    )
    next_r = _write_sensitivity_grid(
        next_r,
        "2. MONSOON WEATHER — Order NCM (₹) across AOV (₹149–₹399) & Rider Payout (₹20–₹50) [Includes Monsoon Surge & Refund Risk]",
        is_monsoon=True,
    )

    # Threshold ₹199 vs ₹249 comparison table at bottom of Sensitivity sheet
    ws_sa.merge_cells(start_row=next_r, start_column=1, end_row=next_r, end_column=6)
    t_cell = ws_sa.cell(row=next_r, column=1, value="3. FREE-DELIVERY THRESHOLD SCENARIO: ₹199 vs ₹249 Across Basket Bands (Normal Weather, Rider = Inputs!C9)")
    t_cell.font = FONT_SUBHDR
    t_cell.fill = SUBHDR_FILL
    hdr_r = next_r + 1
    for c_i, h in enumerate(["Basket AOV", "NCM @ ₹199 Threshold", "NCM @ ₹249 Threshold", "Delta (₹249 - ₹199)", "Fee Impact"], start=1):
        c = ws_sa.cell(row=hdr_r, column=c_i, value=h)
        c.font = FONT_HDR
        c.fill = SLATE_FILL
        c.border = THIN_BORDER

    for i, aov in enumerate([174, 199, 224, 249, 274, 299], start=hdr_r + 1):
        ws_sa.cell(row=i, column=1, value=aov).number_format = INR_INT_FMT
        ws_sa.cell(row=i, column=2, value=f"=($A{i}*Inputs!$C$5)+Inputs!$C$6+IF($A{i}<199,25,0)+(Inputs!$C$13*0.4)-Inputs!$C$8-Inputs!$C$9-Inputs!$C$11-Inputs!$C$12").number_format = INR_FMT
        ws_sa.cell(row=i, column=3, value=f"=($A{i}*Inputs!$C$5)+Inputs!$C$6+IF($A{i}<249,25,0)+(Inputs!$C$13*0.4)-Inputs!$C$8-Inputs!$C$9-Inputs!$C$11-Inputs!$C$12").number_format = INR_FMT
        ws_sa.cell(row=i, column=4, value=f"=C{i}-B{i}").number_format = INR_FMT
        ws_sa.cell(row=i, column=5, value=f'=IF(D{i}>0, "+₹25 Delivery Fee Captured", "No Change")')
        for c_i in range(1, 6):
            ws_sa.cell(row=i, column=c_i).border = THIN_BORDER
            ws_sa.cell(row=i, column=c_i).font = FONT_BODY

    # Auto-fit column widths across all sheets
    for ws in wb.worksheets:
        ws.freeze_panes = "A4"
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.row == 1:
                    continue
                val_str = str(cell.value or "")
                if val_str.startswith("="):
                    val_str = "₹1,00,000.00"
                max_len = max(max_len, len(val_str))
            ws.column_dimensions[col_letter].width = min(max(max_len + 4, 14), 48)

    wb.save(output_path)
    logger.info("Generated Excel Unit Economics Simulator at %s", output_path)
    return output_path


if __name__ == "__main__":
    p = build_excel_simulator()
    print(f"Saved: {p}")
