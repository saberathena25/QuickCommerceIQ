"""Build a real, openable Power BI Project (QuickCommerceIQ.pbip) using TMDL + PBIR."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from python.config import PROJECT_ROOT, get_logger

logger = get_logger(__name__)


def _uid(seed_str: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"quickcommerceiq.{seed_str}"))


def _pbi_hex(seed_str: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"quickcommerceiq.pbi.{seed_str}").hex[:20]


def _pandas_dtype_to_tmdl(dtype) -> tuple[str, str, str | None]:
    """Map pandas dtype to (tmdl_dataType, M_type, formatString)."""
    s = str(dtype)
    if "bool" in s:
        return "boolean", "type logical", None
    if "int" in s:
        return "int64", "Int64.Type", "0"
    if "float" in s:
        return "double", "type number", "#,##0.00"
    return "string", "type text", None


def _build_tmdl_table(
    table_name: str,
    csv_path: Path,
    measures: list[tuple[str, str, str]] | None = None,
    col_overrides: dict[str, tuple[str, str]] | None = None,
) -> str:
    """Generate a valid TMDL table definition reading a CSV via Power Query M."""
    df = pd.read_csv(csv_path, nrows=500)
    col_overrides = col_overrides or {}

    lines = [
        f"table {table_name}",
        f"\tlineageTag: {_uid('table.' + table_name)}",
        "",
    ]

    # Measures
    if measures:
        for m_name, m_expr, m_fmt in measures:
            lines.append(f"\tmeasure '{m_name}' = {m_expr}")
            if m_fmt:
                lines.append(f"\t\tformatString: {m_fmt}")
            lines.append(f"\t\tlineageTag: {_uid('measure.' + table_name + '.' + m_name)}")
            lines.append("")

    # Columns + M type transformations
    m_types = []
    for col in df.columns:
        if col in col_overrides:
            tmdl_type, m_type = col_overrides[col]
            fmt = None
        else:
            tmdl_type, m_type, fmt = _pandas_dtype_to_tmdl(df[col].dtype)

        # Force IDs/dates/pincodes to string so they never auto-sum
        if col.endswith("_id") or col in ("pincode", "year_month", "full_date", "order_date_ist", "registration_date", "first_order_date", "cohort_month"):
            tmdl_type, m_type, fmt = "string", "type text", None
        if col == "date_time_sk":
            tmdl_type, m_type, fmt = "int64", "Int64.Type", "0"

        m_types.append(f'{{"{col}", {m_type}}}')

        summarize = "sum" if (tmdl_type in ("int64", "double") and not (col.endswith("_sk") or col in ("hour_ist", "month", "year", "quarter", "day_of_week", "week_of_year", "month_number"))) else "none"

        col_header = f"'{col}'" if " " in col else col
        lines.append(f"\tcolumn {col_header}")
        lines.append(f"\t\tdataType: {tmdl_type}")
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")
        lines.append(f"\t\tlineageTag: {_uid('col.' + table_name + '.' + col)}")
        lines.append(f"\t\tsummarizeBy: {summarize}")
        lines.append(f"\t\tsourceColumn: {col}")
        lines.append("")
        lines.append("\t\tannotation SummarizationSetBy = Automatic")
        lines.append("")

    win_path = str(csv_path.resolve()).replace("\\", "\\\\")
    m_type_list = ", ".join(m_types)
    lines.extend([
        f"\tpartition {table_name} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\tlet",
        f'\t\t\t\tSource = Csv.Document(File.Contents("{win_path}"), [Delimiter=",", Columns={len(df.columns)}, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        '\t\t\t\t#"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
        f'\t\t\t\t#"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{{m_type_list}}})',
        "\t\t\tin",
        '\t\t\t\t#"Changed Type"',
        "",
    ])
    return "\n".join(lines)


def _col_field(entity: str, prop: str) -> dict[str, Any]:
    return {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": entity}},
                "Property": prop,
            }
        },
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop,
    }


def _meas_field(entity: str, prop: str) -> dict[str, Any]:
    return {
        "field": {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": entity}},
                "Property": prop,
            }
        },
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop,
    }


def _make_visual(
    vis_id: str,
    visual_type: str,
    x: float,
    y: float,
    w: float,
    h: float,
    z: int,
    title: str,
    query_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": vis_id,
        "position": {
            "x": x,
            "y": y,
            "z": z,
            "width": w,
            "height": h,
            "tabOrder": z,
        },
        "visual": {
            "visualType": visual_type,
            "query": {"queryState": query_state},
            "visualContainerObjects": {
                "title": [
                    {
                        "properties": {
                            "show": {"expr": {"Literal": {"Value": "true"}}},
                            "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
                        }
                    }
                ]
            },
        },
    }


def build_powerbi_project() -> Path:
    """Create QuickCommerceIQ.pbip, QuickCommerceIQ.SemanticModel, and QuickCommerceIQ.Report."""
    dash_dir = PROJECT_ROOT / "dashboard"
    proc_dir = PROJECT_ROOT / "data" / "processed"
    rep_dir = PROJECT_ROOT / "reports"

    pbip_file = dash_dir / "QuickCommerceIQ.pbip"
    sm_dir = dash_dir / "QuickCommerceIQ.SemanticModel"
    sm_def = sm_dir / "definition"
    sm_tables = sm_def / "tables"
    rpt_dir = dash_dir / "QuickCommerceIQ.Report"
    rpt_def = rpt_dir / "definition"
    rpt_pages = rpt_def / "pages"
    static_res = rpt_dir / "StaticResources" / "RegisteredResources"

    for d in [sm_tables, rpt_pages, static_res]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. .pbip pointer
    pbip_file.write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                "version": "1.0",
                "artifacts": [{"report": {"path": "QuickCommerceIQ.Report"}}],
                "settings": {"enableAutoRecovery": True},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 2. SemanticModel metadata & TMDL
    (sm_dir / "definition.pbism").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
                "version": "4.2",
                "settings": {"qnaEnabled": True},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (sm_def / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n", encoding="utf-8")

    table_specs: list[tuple[str, Path, list[tuple[str, str, str]] | None]] = [
        (
            "fact_orders",
            proc_dir / "fact_orders_pbi.csv",
            [
                ("Total Orders", "COUNTROWS(fact_orders)", "#,##0"),
                ("Delivered Orders", 'CALCULATE(COUNTROWS(fact_orders), fact_orders[order_status] = "DELIVERED")', "#,##0"),
                ("Total GMV (INR)", "SUM(fact_orders[cart_value])", '"₹"#,##,##0'),
                ("Total NCM (INR)", "SUM(fact_orders[net_contribution_margin])", '"₹"#,##,##0.00'),
                ("NCM per Order (INR)", "DIVIDE([Total NCM (INR)], [Total Orders], 0)", '"₹"#,##0.00'),
                ("Average Delivery Time (Min)", 'CALCULATE(AVERAGE(fact_orders[total_delivery_minutes]), fact_orders[order_status] = "DELIVERED")', "0.00"),
                ("Avg Picking Time (Min)", 'CALCULATE(AVERAGE(fact_orders[picking_minutes]), fact_orders[order_status] = "DELIVERED")', "0.00"),
                ("Avg Rider Assignment Time (Min)", 'CALCULATE(AVERAGE(fact_orders[assignment_minutes]), fact_orders[order_status] = "DELIVERED")', "0.00"),
                ("Avg Transit Time (Min)", 'CALCULATE(AVERAGE(fact_orders[transit_minutes]), fact_orders[order_status] = "DELIVERED")', "0.00"),
                ("SLA Breach Count", 'CALCULATE(COUNTROWS(fact_orders), fact_orders[order_status] = "DELIVERED", fact_orders[is_sla_breach] = TRUE())', "#,##0"),
                ("SLA Breach Rate %", "DIVIDE([SLA Breach Count], [Delivered Orders], 0)", "0.00%"),
            ],
        ),
        ("dim_dark_stores", proc_dir / "dim_dark_stores_clean.csv", None),
        ("dim_date_time", proc_dir / "dim_date_time.csv", None),
        ("dim_customers", proc_dir / "dim_customers_clean.csv", None),
        ("analytics_unit_economics_waterfall", proc_dir / "analytics_unit_economics_waterfall.csv", None),
        ("analytics_store_ranking_root_cause", proc_dir / "analytics_store_ranking_root_cause.csv", None),
        ("analytics_ncm_monthly", proc_dir / "analytics_ncm_monthly.csv", None),
        ("analytics_sla_by_hour", proc_dir / "analytics_sla_by_hour.csv", None),
        ("analytics_sla_by_weather", proc_dir / "analytics_sla_by_weather.csv", None),
        (
            "analytics_stockout_store_sku_hour",
            proc_dir / "analytics_stockout_store_sku_hour.csv",
            [
                ("Estimated Lost GMV (INR)", "SUM(analytics_stockout_store_sku_hour[estimated_lost_gmv_inr])", '"₹"#,##,##0.00'),
                ("Estimated Lost Margin (INR)", "SUM(analytics_stockout_store_sku_hour[estimated_lost_margin_inr])", '"₹"#,##,##0.00'),
            ],
        ),
        (
            "analytics_cohort_retention_matrix",
            proc_dir / "analytics_cohort_retention_matrix.csv",
            [
                ("Cohort Retention %", "DIVIDE(SUM(analytics_cohort_retention_matrix[active_customers]), SUM(analytics_cohort_retention_matrix[cohort_size]), 0)", "0.0%"),
            ],
        ),
        ("analytics_cohort_retention_by_sla", proc_dir / "analytics_cohort_retention_by_sla.csv", None),
        ("experiment_results", rep_dir / "experiment_results.csv", None),
    ]

    model_lines = [
        "model Model",
        "\tculture: en-US",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: en-IN",
        "",
    ]
    for t_name, csv_p, measures in table_specs:
        model_lines.append(f"ref table {t_name}")
        tmdl_text = _build_tmdl_table(t_name, csv_p, measures=measures)
        (sm_tables / f"{t_name}.tmdl").write_text(tmdl_text, encoding="utf-8")

    (sm_def / "model.tmdl").write_text("\n".join(model_lines) + "\n", encoding="utf-8")

    # Star Schema relationships
    rels = [
        ("fact_orders", "store_id", "dim_dark_stores", "store_id"),
        ("fact_orders", "customer_id", "dim_customers", "customer_id"),
        ("fact_orders", "date_time_sk", "dim_date_time", "date_time_sk"),
        ("analytics_store_ranking_root_cause", "store_id", "dim_dark_stores", "store_id"),
        ("analytics_stockout_store_sku_hour", "store_id", "dim_dark_stores", "store_id"),
    ]
    rel_lines = []
    for f_tbl, f_col, t_tbl, t_col in rels:
        rel_lines.append(f"relationship {_uid(f'rel.{f_tbl}.{f_col}')}")
        rel_lines.append(f"\tfromColumn: {f_tbl}.{f_col}")
        rel_lines.append(f"\ttoColumn: {t_tbl}.{t_col}")
        rel_lines.append("")
    (sm_def / "relationships.tmdl").write_text("\n".join(rel_lines), encoding="utf-8")

    # 3. Report PBIR definition
    (rpt_dir / "definition.pbir").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                "version": "4.0",
                "datasetReference": {"byPath": {"path": "../QuickCommerceIQ.SemanticModel"}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (rpt_def / "version.json").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
                "version": "2.0.0",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    theme_dst = static_res / "QuickCommerceIQ_Theme.json"
    shutil.copyfile(dash_dir / "QuickCommerceIQ_Theme.json", theme_dst)

    (rpt_def / "report.json").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.1.0/schema.json",
                "themeCollection": {
                    "baseTheme": {
                        "name": "CY24SU10",
                        "reportVersionAtImport": {"visual": "2.1.0", "report": "3.1.0", "page": "2.0.0"},
                        "type": "SharedResources",
                    },
                    "customTheme": {
                        "name": "QuickCommerceIQ_Theme.json",
                        "reportVersionAtImport": {"visual": "2.1.0", "report": "3.1.0", "page": "2.0.0"},
                        "type": "RegisteredResources",
                    },
                },
                "resourcePackages": [
                    {
                        "name": "RegisteredResources",
                        "type": "RegisteredResources",
                        "items": [{"name": "QuickCommerceIQ_Theme.json", "path": "QuickCommerceIQ_Theme.json", "type": "CustomTheme"}],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    p1_id = _pbi_hex("page1")
    p2_id = _pbi_hex("page2")
    p3_id = _pbi_hex("page3")

    (rpt_pages / "pages.json").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
                "pageOrder": [p1_id, p2_id, p3_id],
                "activePageName": p1_id,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    def _write_page(pid: str, display_name: str, visuals: list[dict[str, Any]]) -> None:
        p_dir = rpt_pages / pid
        v_dir = p_dir / "visuals"
        v_dir.mkdir(parents=True, exist_ok=True)
        (p_dir / "page.json").write_text(
            json.dumps(
                {
                    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
                    "name": pid,
                    "displayName": display_name,
                    "displayOption": "FitToPage",
                    "height": 720,
                    "width": 1280,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        for vis in visuals:
            one_v = v_dir / vis["name"]
            one_v.mkdir(parents=True, exist_ok=True)
            (one_v / "visual.json").write_text(json.dumps(vis, indent=2), encoding="utf-8")

    # Page 1: Executive Landing
    p1_visuals = [
        _make_visual(_pbi_hex("p1_slicer_city"), "slicer", 20, 12, 230, 75, 1, "City", {"Values": {"projections": [_col_field("dim_dark_stores", "city")]}}),
        _make_visual(_pbi_hex("p1_slicer_weather"), "slicer", 265, 12, 230, 75, 2, "Weather", {"Values": {"projections": [_col_field("fact_orders", "weather_tag")]}}),
        _make_visual(_pbi_hex("p1_slicer_pay"), "slicer", 510, 12, 230, 75, 3, "Payment Mode", {"Values": {"projections": [_col_field("fact_orders", "payment_mode")]}}),
        _make_visual(_pbi_hex("p1_slicer_month"), "slicer", 755, 12, 230, 75, 4, "Month", {"Values": {"projections": [_col_field("dim_date_time", "year_month")]}}),
        _make_visual(_pbi_hex("p1_kpi_orders"), "card", 20, 98, 236, 95, 5, "Total Orders", {"Values": {"projections": [_meas_field("fact_orders", "Total Orders")]}}),
        _make_visual(_pbi_hex("p1_kpi_ncm"), "card", 270, 98, 236, 95, 6, "NCM per Order (INR)", {"Values": {"projections": [_meas_field("fact_orders", "NCM per Order (INR)")]}}),
        _make_visual(_pbi_hex("p1_kpi_sla"), "card", 520, 98, 236, 95, 7, "SLA Breach Rate %", {"Values": {"projections": [_meas_field("fact_orders", "SLA Breach Rate %")]}}),
        _make_visual(_pbi_hex("p1_kpi_deliv"), "card", 770, 98, 236, 95, 8, "Avg Delivery Time (Min)", {"Values": {"projections": [_meas_field("fact_orders", "Average Delivery Time (Min)")]}}),
        _make_visual(_pbi_hex("p1_kpi_gmv_lost"), "card", 1020, 98, 240, 95, 9, "Peak Lost GMV (INR)", {"Values": {"projections": [_meas_field("analytics_stockout_store_sku_hour", "Estimated Lost GMV (INR)")]}}),
        _make_visual(
            _pbi_hex("p1_trend"),
            "lineClusteredColumnComboChart",
            20, 205, 610, 245, 10,
            "Monthly Orders vs NCM per Order (INR)",
            {
                "Category": {"projections": [_col_field("dim_date_time", "year_month")]},
                "ColumnY": {"projections": [_meas_field("fact_orders", "Total Orders")]},
                "LineY": {"projections": [_meas_field("fact_orders", "NCM per Order (INR)")]},
            },
        ),
        _make_visual(
            _pbi_hex("p1_waterfall"),
            "clusteredBarChart",
            645, 205, 615, 245, 11,
            "Unit Economics Bridge (Avg INR per Order)",
            {
                "Category": {"projections": [_col_field("analytics_unit_economics_waterfall", "component")]},
                "Y": {"projections": [_col_field("analytics_unit_economics_waterfall", "avg_inr_per_order")]},
            },
        ),
        _make_visual(
            _pbi_hex("p1_bleeding"),
            "clusteredBarChart",
            20, 462, 520, 245, 12,
            "Store Profitability (Avg NCM per Order INR)",
            {
                "Category": {"projections": [_col_field("dim_dark_stores", "store_name")]},
                "Y": {"projections": [_meas_field("fact_orders", "NCM per Order (INR)")]},
            },
        ),
        _make_visual(
            _pbi_hex("p1_table"),
            "tableEx",
            555, 462, 705, 245, 13,
            "Dark Store Root-Cause Diagnostics",
            {
                "Values": {
                    "projections": [
                        _col_field("analytics_store_ranking_root_cause", "store_name"),
                        _col_field("analytics_store_ranking_root_cause", "city"),
                        _col_field("analytics_store_ranking_root_cause", "avg_ncm_per_order_inr"),
                        _col_field("analytics_store_ranking_root_cause", "net_store_operating_profit_inr"),
                        _col_field("analytics_store_ranking_root_cause", "sla_breach_pct"),
                        _col_field("analytics_store_ranking_root_cause", "primary_bottleneck"),
                        _col_field("analytics_store_ranking_root_cause", "root_cause_tags"),
                    ]
                }
            },
        ),
    ]
    _write_page(p1_id, "Executive Landing", p1_visuals)

    # Page 2: Operations & SLA Deep-Dive
    p2_visuals = [
        _make_visual(
            _pbi_hex("p2_hourly"),
            "clusteredColumnChart",
            20, 20, 610, 320, 1,
            "Hourly SLA Breach Rate % (IST 0–23)",
            {
                "Category": {"projections": [_col_field("dim_date_time", "hour_ist")]},
                "Y": {"projections": [_meas_field("fact_orders", "SLA Breach Rate %")]},
            },
        ),
        _make_visual(
            _pbi_hex("p2_stages"),
            "stackedBarChart",
            645, 20, 615, 320, 2,
            "Delivery Stage Decomposition by City (Minutes)",
            {
                "Category": {"projections": [_col_field("dim_dark_stores", "city")]},
                "Y": {
                    "projections": [
                        _meas_field("fact_orders", "Avg Picking Time (Min)"),
                        _meas_field("fact_orders", "Avg Rider Assignment Time (Min)"),
                        _meas_field("fact_orders", "Avg Transit Time (Min)"),
                    ]
                },
            },
        ),
        _make_visual(
            _pbi_hex("p2_weather"),
            "clusteredColumnChart",
            20, 355, 480, 345, 3,
            "Normal vs Monsoon vs Heavy Rain SLA Breach %",
            {
                "Category": {"projections": [_col_field("fact_orders", "weather_tag")]},
                "Y": {"projections": [_meas_field("fact_orders", "SLA Breach Rate %")]},
            },
        ),
        _make_visual(
            _pbi_hex("p2_stockout_tbl"),
            "tableEx",
            515, 355, 745, 345, 4,
            "Peak-Hour (7–10 PM) Stockout Lost GMV by Store & SKU",
            {
                "Values": {
                    "projections": [
                        _col_field("analytics_stockout_store_sku_hour", "store_name"),
                        _col_field("analytics_stockout_store_sku_hour", "sku_name"),
                        _col_field("analytics_stockout_store_sku_hour", "hour_ist"),
                        _col_field("analytics_stockout_store_sku_hour", "stockout_hours"),
                        _col_field("analytics_stockout_store_sku_hour", "estimated_lost_units"),
                        _col_field("analytics_stockout_store_sku_hour", "estimated_lost_gmv_inr"),
                        _col_field("analytics_stockout_store_sku_hour", "estimated_lost_margin_inr"),
                    ]
                }
            },
        ),
    ]
    _write_page(p2_id, "Operations & SLA Deep-Dive", p2_visuals)

    # Page 3: Growth, Cohorts & A/B Test Readout
    p3_visuals = [
        _make_visual(
            _pbi_hex("p3_coh_line"),
            "lineChart",
            20, 20, 610, 325, 1,
            "Cohort Retention Curve by First-Order SLA Segment",
            {
                "Category": {"projections": [_col_field("analytics_cohort_retention_by_sla", "month_number")]},
                "Series": {"projections": [_col_field("analytics_cohort_retention_by_sla", "sla_segment")]},
                "Y": {"projections": [_col_field("analytics_cohort_retention_by_sla", "retention_pct")]},
            },
        ),
        _make_visual(
            _pbi_hex("p3_coh_matrix"),
            "pivotTable",
            645, 20, 615, 325, 2,
            "Customer Cohort Retention Matrix (Months 0–6)",
            {
                "Rows": {"projections": [_col_field("analytics_cohort_retention_matrix", "cohort_month")]},
                "Columns": {"projections": [_col_field("analytics_cohort_retention_matrix", "month_number")]},
                "Values": {"projections": [_meas_field("analytics_cohort_retention_matrix", "Cohort Retention %")]},
            },
        ),
        _make_visual(
            _pbi_hex("p3_ab_chart"),
            "clusteredColumnChart",
            20, 360, 480, 340, 3,
            "A/B Test: ₹199 Control vs ₹249 Treatment",
            {
                "Category": {"projections": [_col_field("experiment_results", "metric")]},
                "Y": {
                    "projections": [
                        _col_field("experiment_results", "control_value"),
                        _col_field("experiment_results", "treatment_value"),
                    ]
                },
            },
        ),
        _make_visual(
            _pbi_hex("p3_ab_table"),
            "tableEx",
            515, 360, 745, 340, 4,
            "A/B Statistical Readout (SRM Passed | Recommendation: TARGETED_ROLLOUT_OR_229_TEST)",
            {
                "Values": {
                    "projections": [
                        _col_field("experiment_results", "metric"),
                        _col_field("experiment_results", "role"),
                        _col_field("experiment_results", "control_value"),
                        _col_field("experiment_results", "treatment_value"),
                        _col_field("experiment_results", "absolute_diff"),
                        _col_field("experiment_results", "relative_lift_pct"),
                        _col_field("experiment_results", "p_value"),
                        _col_field("experiment_results", "significant_at_5pct"),
                    ]
                }
            },
        ),
    ]
    _write_page(p3_id, "Growth, Cohorts & AB Test", p3_visuals)

    logger.info("Built Power BI Project (.pbip) at %s", pbip_file)
    return pbip_file


if __name__ == "__main__":
    p = build_powerbi_project()
    print(f"Created Power BI Project: {p}")
