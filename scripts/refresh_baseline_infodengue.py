"""
Baseline-builder for the InfoDengue-backed Brazil region (Rio de Janeiro).
Pulls InfoDengue's full history, loads it into raw_readings, and computes
+ stores the current operative baseline -- same idea as run_pipeline.py
for OpenDengue, just pointed at a different ingest source.

Run this occasionally (every ~6 months is plenty): baselines are built
from years of history and don't need to be rebuilt every week. The
week-to-week check is scripts/check_current_week.py, which is cheap and
meant to run weekly.

Usage:
    python -m scripts.refresh_baseline_infodengue
"""

import pandas as pd
from sqlalchemy import text

from src.analysis.baselines import compute_current_baselines, store_baselines
from src.analysis.stats import add_period_index, compute_trailing_baseline, flag_anomalies
from src.db.connection import get_engine
from src.db.load import load_readings
from src.ingest.download_infodengue import CITY_NAME, REGION, load_clean_infodengue_history


def main():
    print(f"Downloading full InfoDengue history for {CITY_NAME}...")
    data = load_clean_infodengue_history()
    print(f"  {len(data)} weekly rows, {data['period_start'].min()} to {data['period_start'].max()}")

    engine = get_engine()

    print("Loading into raw_readings...")
    n_loaded = load_readings(data, engine)
    print(f"  upserted {n_loaded} rows")

    readings = pd.read_sql(
        text("SELECT * FROM raw_readings WHERE disease = 'dengue' AND region = :region"),
        engine,
        params={"region": REGION},
    )
    readings = add_period_index(readings, date_col="period_start")

    print("Computing current operative baselines...")
    current_baselines = compute_current_baselines(readings)
    n_baselines = store_baselines(current_baselines, engine)
    print(f"  stored {n_baselines} baseline rows")

    print("\nBacktesting anomaly detection across full history...")
    backtest = compute_trailing_baseline(readings)
    anomalies = flag_anomalies(backtest).sort_values("period_start")

    if anomalies.empty:
        print("No anomalies found.")
        return

    print(f"\n{len(anomalies)} anomalous weeks flagged (|z| >= 2.5):\n")
    cols = ["period_start", "value", "baseline_mean", "baseline_stddev", "z_score"]
    with pd.option_context("display.float_format", "{:.1f}".format):
        print(anomalies[cols].to_string(index=False))


if __name__ == "__main__":
    main()
