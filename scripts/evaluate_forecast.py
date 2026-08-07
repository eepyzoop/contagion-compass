"""
Phase 6b: trains the Prophet forecasting model on the full stored history for
a disease/region/metric, holds out the most recent `--test-weeks` weeks, and
reports MAE/RMSE -- the documented evaluation this phase asks for, not just a
model plugged in untested.

Usage:
    python -m scripts.evaluate_forecast [--test-weeks 52]
"""

import argparse

import pandas as pd
from sqlalchemy import text

from src.analysis.forecast import evaluate
from src.db.connection import get_engine
from src.ingest.download_infodengue import DISEASE, METRIC, REGION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-weeks", type=int, default=52)
    args = parser.parse_args()

    engine = get_engine()
    history = pd.read_sql(
        text(
            """
            SELECT period_start, value FROM raw_readings
            WHERE disease = :disease AND region = :region AND metric = :metric
            ORDER BY period_start
            """
        ),
        engine,
        params={"disease": DISEASE, "region": REGION, "metric": METRIC},
    )
    print(f"Loaded {len(history)} weekly readings for {DISEASE}/{REGION}/{METRIC}.")

    result = evaluate(history, test_weeks=args.test_weeks)
    print(
        f"Held out the last {result['n_test_weeks']} weeks -- "
        f"MAE: {result['mae']:.1f}, RMSE: {result['rmse']:.1f}"
    )


if __name__ == "__main__":
    main()
