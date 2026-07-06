"""
Computes the *current operative* baseline for each (disease, region, metric,
period_index) -- the mean/std an incoming reading should be judged against
right now -- and stores it in the `baselines` table for the agent (Phase 2+)
to query.
"""

import pandas as pd
from sqlalchemy import text

from src.analysis.stats import DEFAULT_TRAILING_YEARS, add_period_index
from src.db.connection import get_engine, init_schema

UPSERT_SQL = text(
    """
    INSERT INTO baselines
        (disease, region, metric, resolution, period_index,
         historical_mean, historical_stddev, n_observations)
    VALUES
        (:disease, :region, :metric, :resolution, :period_index,
         :historical_mean, :historical_stddev, :n_observations)
    ON CONFLICT (disease, region, metric, resolution, period_index)
    DO UPDATE SET
        historical_mean = EXCLUDED.historical_mean,
        historical_stddev = EXCLUDED.historical_stddev,
        n_observations = EXCLUDED.n_observations,
        computed_at = now()
    """
)


def compute_current_baselines(
    df: pd.DataFrame,
    trailing_years: int = DEFAULT_TRAILING_YEARS,
) -> pd.DataFrame:
    """
    Uses the most recent `trailing_years` years present in `df` for each
    (disease, region, metric, period_index) to compute the baseline that
    should apply going forward. `df` must already have `year`/`period_index`
    (see add_period_index) and a `resolution` column.
    """
    rows = []
    group_cols = ["disease", "region", "metric", "resolution", "period_index"]
    for keys, group in df.groupby(group_cols):
        latest_year = group["year"].max()
        window = group[group["year"] > latest_year - trailing_years]
        if len(window) < 2:
            continue
        row = dict(zip(group_cols, keys))
        row["historical_mean"] = window["value"].mean()
        row["historical_stddev"] = window["value"].std(ddof=1)
        row["n_observations"] = len(window)
        rows.append(row)
    return pd.DataFrame(rows)


def store_baselines(baseline_df: pd.DataFrame, engine=None) -> int:
    engine = engine or get_engine()
    init_schema(engine)
    records = baseline_df.to_dict(orient="records")
    with engine.begin() as conn:
        for record in records:
            conn.execute(UPSERT_SQL, record)
    return len(records)


if __name__ == "__main__":
    from src.db.connection import get_engine

    engine = get_engine()
    readings = pd.read_sql(
        "SELECT * FROM raw_readings WHERE disease = 'dengue'", engine
    )
    readings = add_period_index(readings, date_col="period_start")
    baselines = compute_current_baselines(readings)
    n = store_baselines(baselines, engine)
    print(f"Stored {n} baseline rows")
