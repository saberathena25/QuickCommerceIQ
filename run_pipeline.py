"""Master end-to-end orchestrator for QuickCommerceIQ."""

from __future__ import annotations

import argparse

from python.analytics.engine import run_all_analytics
from python.analytics.excel_simulator import build_excel_simulator
from python.analytics.executive_report import generate_executive_memo_pdf
from python.config import get_logger
from python.experiments.ab_testing import run_ab_experiment_analysis
from python.generators.generate_all import run_data_generation
from python.ingestion.etl_pipeline import run_etl_pipeline

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="QuickCommerceIQ End-to-End Analytics Pipeline")
    parser.add_argument("--skip-generate", action="store_true", help="Skip synthetic CSV generation and reuse existing raw files.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible synthetic generation.")
    args = parser.parse_args()

    if not args.skip_generate:
        logger.info("Step 1/6: Generating synthetic datasets...")
        run_data_generation(seed=args.seed)
    else:
        logger.info("Step 1/6: Skipping generation (--skip-generate).")

    logger.info("Step 2/6: Running ETL cleaning, quarantine, quality gates, and warehouse load...")
    run_etl_pipeline(strict_gate=True)

    logger.info("Step 3/6: Running Core Business Analytics...")
    run_all_analytics()

    logger.info("Step 4/6: Running Statistical A/B Experimentation Framework...")
    run_ab_experiment_analysis()

    logger.info("Step 5/6: Building Excel Unit Economics Simulator...")
    build_excel_simulator()

    logger.info("Step 6/6: Generating Executive Memo PDF & Charts...")
    generate_executive_memo_pdf()

    logger.info("QuickCommerceIQ end-to-end pipeline completed successfully.")


if __name__ == "__main__":
    main()
