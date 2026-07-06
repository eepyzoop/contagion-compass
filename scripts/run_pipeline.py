"""
Phase 1 deliverable: pulls fresh dengue data, stores it, and prints any
statistical anomalies found -- no LLM involved yet (that's Phase 2).

Usage:
    python -m scripts.run_pipeline
"""

import pandas as pd

from src.analysis.baselines import compute_current_baselines, store_baselines
from src.analysis.stats import add_period_index, compute_trailing_baseline, flag_anomalies
from src.db.connection import get_engine
from src.db.load import load_readings
from src.ingest.download_opendengue import load_clean_national_dengue


def main():
    print("Downloading + cleaning OpenDengue national extract...")
    data = load_clean_national_dengue()
    print(f"  {len(data)} rows across {data['region'].nunique()} countries")

    engine = get_engine()

    print("Loading into raw_readings...")
    n_loaded = load_readings(data, engine)
    print(f"  upserted {n_loaded} rows")

    readings = pd.read_sql("SELECT * FROM raw_readings WHERE disease = 'dengue'", engine)
    readings = add_period_index(readings, date_col="period_start")

    print("Computing current operative baselines (for Phase 2's agent)...")
    current_baselines = compute_current_baselines(readings)
    n_baselines = store_baselines(current_baselines, engine)
    print(f"  stored {n_baselines} baseline rows")

    print("\nBacktesting anomaly detection across full history...")
    backtest = compute_trailing_baseline(readings)
    anomalies = flag_anomalies(backtest).sort_values(["region", "period_start"])

    if anomalies.empty:
        print("No anomalies found.")
        return

    print(f"\n{len(anomalies)} anomalous weeks flagged (|z| >= 2.5):\n")
    cols = ["region", "period_start", "value", "baseline_mean", "baseline_stddev", "z_score"]
    with pd.option_context("display.float_format", "{:.1f}".format):
        print(anomalies[cols].to_string(index=False))


if __name__ == "__main__":
    main()
