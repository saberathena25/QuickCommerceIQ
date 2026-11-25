# QuickCommerceIQ — Project Status

Last Updated: 2026-11-25

## Completed Phases
- **Phase 1 — Inspection and Project Setup:** Repository layout, `requirements.txt`, `.env.example`, `.gitignore`, `docker-compose.yml`, YAML/JSON configs, and `python/config.py`.
- **Phase 2 — Data Generation Engine:** Reproducible generation of 11 raw CSV datasets (`179,887` raw orders, `468,730` order items, `1,177,600` inventory snapshots, `42,000` customers, `600` riders, `650` SKUs, `25` dark stores + `1` bogus store, weather & rider logs, A/B assignments & events) plus SCD2 history and `data/sample/` previews.
- **Phase 3 — PostgreSQL Star Schema DDL:** `sql/ddl/01_init_warehouse.sql`, `02_staging_and_audit.sql`, `03_indexes_and_constraints.sql`, `sql/transformations/01_scd2_upsert_examples.sql`, and dual PostgreSQL/SQLite `python/db.py`.
- **Phase 4 — Python ETL & Data Quality:** Normalization, deduplication, UTC/IST standardization, lifecycle & financial validation, quarantine (`23,292` records), critical quality gate enforcement, and `reports/data_quality_report.json`.
- **Phase 5 — Core Business Analytics:** PostgreSQL analytical SQL (`sql/analytics/01..05`) and `python/analytics/engine.py` producing Unit Economics, SLA decomposition, rolling 30-min congestion, Cohort Retention (Months 0–6), Peak Stockout Lost GMV, and Store Ranking & Root-Cause tags.
- **Phase 6 — Statistical A/B Testing:** Deterministic SHA-256 randomization, ITT analysis on `42,000` users, SRM Chi-Square, Welch's t-test, Two-Proportion Z-Tests, Mann-Whitney U, Bootstrap 95% CIs, and `reports/experiment_results.csv` + `reports/ab_experiment_report.json`.
- **Phase 7 — Excel Financial Simulator:** `excel_models/QuickCommerceIQ_Unit_Economics_Simulator.xlsx` with 4 formula-driven worksheets (`Inputs`, `Unit_Economics`, `BreakEven_Model`, `Sensitivity_Analysis`), INR formatting, data validations, and conditional formatting.
- **Phase 8 — Power BI Reporting Layer:** `sql/analytics/powerbi_views.sql`, `dashboard/dax_measures.md`, and `dashboard/dashboard_documentation.md` specifying all 3 executive pages.
- **Phase 9 — Testing & Documentation:** `pytest` suite (16 passing tests), `run_pipeline.py`, `reports/executive_memo.pdf`, charts in `reports/figures/`, `docs/*.md`, and `README.md`.

## Pending Phases
- None (all phases implemented and verified locally).

## Known Issues & Environment Notes
- PostgreSQL / Docker and Power BI Desktop are not installed on this local Windows machine; therefore, runtime SQL execution was verified against the schema-aligned local SQLite mirror (`data/processed/quickcommerce_warehouse.db`), and Power BI artifacts consist of PostgreSQL `bi.*` views, DAX measures, and complete build specifications rather than a binary `.pbix`.

## Exact Next Steps (For End User)
1. Optional: Run `docker compose up -d` and execute `python run_pipeline.py` to populate a live PostgreSQL 16 container.
2. Open `excel_models/QuickCommerceIQ_Unit_Economics_Simulator.xlsx` in Microsoft Excel and `reports/executive_memo.pdf`.
3. Import `sql/analytics/powerbi_views.sql` views into Power BI Desktop using `dashboard/dashboard_documentation.md`.
