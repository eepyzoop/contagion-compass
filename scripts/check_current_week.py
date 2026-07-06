"""
The cheap, weekly-run half of the two-source design: pulls InfoDengue's
latest available week for Rio de Janeiro, upserts it into raw_readings,
and compares it against the already-stored baseline for that week-of-year
-- purely statistical for now. Phase 2b's LLM layer will wrap this
comparison in actual judgment (is this really worth flagging, or is there
a mundane explanation); for now this just prints the z-score verdict.

Requires scripts/refresh_baseline_infodengue.py to have been run at least
once so a baseline exists to compare against.

Usage:
    python -m scripts.check_current_week
"""

import pandas as pd
from sqlalchemy import text

from src.analysis.stats import DEFAULT_Z_THRESHOLD, add_period_index
from src.db.connection import get_engine
from src.db.load import load_readings
from src.ingest.download_infodengue import DISEASE, METRIC, REGION, fetch_latest_week


def main():
    print("Fetching latest InfoDengue week for Rio de Janeiro...")
    latest = fetch_latest_week()
    row = latest.iloc[0]
    print(f"  {row['period_start']}: {row['value']:.1f} estimated cases")

    engine = get_engine()
    load_readings(latest, engine)

    latest = add_period_index(latest, date_col="period_start")
    period_index = int(latest.iloc[0]["period_index"])

    baseline = pd.read_sql(
        text(
            """
            SELECT historical_mean, historical_stddev, n_observations
            FROM baselines
            WHERE disease = :disease AND region = :region AND metric = :metric
              AND resolution = 'week' AND period_index = :period_index
            """
        ),
        engine,
        params={
            "disease": DISEASE,
            "region": REGION,
            "metric": METRIC,
            "period_index": period_index,
        },
    )

    if baseline.empty:
        print(
            f"\nNo baseline stored yet for week {period_index}. "
            "Run `python -m scripts.refresh_baseline_infodengue` first."
        )
        return

    mean = baseline.iloc[0]["historical_mean"]
    std = baseline.iloc[0]["historical_stddev"]
    n_obs = baseline.iloc[0]["n_observations"]
    z = (row["value"] - mean) / std if std > 0 else float("nan")

    print(f"\nBaseline for week {period_index}: mean={mean:.1f}, stddev={std:.1f} (n={n_obs} years)")
    print(f"z-score: {z:.2f}")

    if abs(z) >= DEFAULT_Z_THRESHOLD:
        print(f"ANOMALY FLAGGED (|z| >= {DEFAULT_Z_THRESHOLD})")
    else:
        print("Within normal range -- no anomaly flagged.")


if __name__ == "__main__":
    main()
