"""
Generic statistical building blocks for surveillance anomaly detection.

Every function here is parameterized by disease/region/metric (or works on
whatever grouping columns are passed in) -- nothing is hardcoded to dengue,
so the same functions serve every disease added in later phases.

Baselines are computed from a trailing window of *prior* years only (no
data leakage from the future), matching how a real monitoring system would
actually operate: "is this week unusual compared to the same week in the
last N years."
"""

import numpy as np
import pandas as pd

DEFAULT_TRAILING_YEARS = 5
DEFAULT_MIN_BASELINE_YEARS = 3
DEFAULT_Z_THRESHOLD = 2.5


def add_period_index(df: pd.DataFrame, date_col: str = "period_start") -> pd.DataFrame:
    """Adds ISO `year` and `period_index` (ISO week number) columns."""
    df = df.copy()
    dates = pd.to_datetime(df[date_col])
    iso = dates.dt.isocalendar()
    df["year"] = iso["year"]
    df["period_index"] = iso["week"]
    return df


def rolling_average(
    df: pd.DataFrame,
    window: int = 4,
    value_col: str = "value",
    group_cols: tuple = ("region",),
    date_col: str = "period_start",
) -> pd.DataFrame:
    """Adds a `rolling_avg` column: trailing mean of `value_col` within each group."""
    df = df.sort_values(list(group_cols) + [date_col]).copy()
    df["rolling_avg"] = df.groupby(list(group_cols))[value_col].transform(
        lambda s: s.rolling(window, min_periods=1).mean()
    )
    return df


def compute_trailing_baseline(
    df: pd.DataFrame,
    group_cols: tuple = ("disease", "region", "metric"),
    value_col: str = "value",
    trailing_years: int = DEFAULT_TRAILING_YEARS,
    min_baseline_years: int = DEFAULT_MIN_BASELINE_YEARS,
) -> pd.DataFrame:
    """
    For every row, computes a baseline mean/std from the same `period_index`
    (e.g. ISO week) in the `trailing_years` years immediately before that
    row's year -- using fewer years if fewer are available, down to
    `min_baseline_years`. Rows without enough prior history get NaN baseline
    and z-score (nothing to compare against yet).

    Expects `df` to already have `year` and `period_index` columns (see
    `add_period_index`). Returns a copy of `df` with `baseline_mean`,
    `baseline_stddev`, `n_baseline_years`, and `z_score` columns added.
    """
    df = df.copy()
    df["baseline_mean"] = np.nan
    df["baseline_stddev"] = np.nan
    df["n_baseline_years"] = 0

    for _, group in df.groupby(list(group_cols) + ["period_index"]):
        group = group.sort_values("year")
        years = group["year"].to_numpy()
        values = group[value_col].to_numpy()

        for i, idx in enumerate(group.index):
            year = years[i]
            window_mask = (years < year) & (years >= year - trailing_years)
            prior_values = values[window_mask]

            if len(prior_values) >= min_baseline_years:
                df.at[idx, "baseline_mean"] = prior_values.mean()
                df.at[idx, "baseline_stddev"] = prior_values.std(ddof=1)
                df.at[idx, "n_baseline_years"] = len(prior_values)

    std = df["baseline_stddev"]
    df["z_score"] = np.where(
        std > 0,
        (df[value_col] - df["baseline_mean"]) / std,
        np.nan,
    )
    return df


def flag_anomalies(
    df: pd.DataFrame, z_threshold: float = DEFAULT_Z_THRESHOLD
) -> pd.DataFrame:
    """Returns rows whose |z_score| meets or exceeds the threshold."""
    return df[df["z_score"].abs() >= z_threshold].copy()
