"""
Self-check on src/analysis/forecast.py's pure logic (no DB/network) -- a
synthetic weekly series with known seasonality, fitted and evaluated the same
way scripts/evaluate_forecast.py and the check_forecast tool do.

Usage:
    python -m tests.test_forecast
"""

import numpy as np
import pandas as pd

from src.analysis.forecast import evaluate, predict_next


def _synthetic_series(n_weeks=260, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2019-01-06", periods=n_weeks, freq="7D")
    seasonal = 100 + 40 * np.sin(np.arange(n_weeks) / 52 * 2 * np.pi)
    noise = rng.normal(0, 5, n_weeks)
    return pd.DataFrame({"period_start": dates, "value": seasonal + noise})


def test_predict_next_returns_one_row_past_the_last_date():
    df = _synthetic_series()
    forecast = predict_next(df, periods=1)
    assert len(forecast) == 1
    assert forecast.iloc[0]["ds"] > pd.Timestamp(df["period_start"].max())
    assert forecast.iloc[0]["yhat_lower"] <= forecast.iloc[0]["yhat"] <= forecast.iloc[0]["yhat_upper"]


def test_evaluate_on_seasonal_series_has_reasonably_low_error():
    df = _synthetic_series()
    result = evaluate(df, test_weeks=52)
    assert result["n_test_weeks"] == 52
    # noise stddev is 5; a model that's actually learned the seasonality
    # should land well under the series' ~40-unit seasonal swing.
    assert result["mae"] < 15
    assert result["rmse"] < 20


def test_evaluate_rejects_too_few_rows():
    df = _synthetic_series(n_weeks=30)
    try:
        evaluate(df, test_weeks=52)
    except ValueError:
        return
    raise AssertionError("expected ValueError for insufficient history")


if __name__ == "__main__":
    test_predict_next_returns_one_row_past_the_last_date()
    test_evaluate_on_seasonal_series_has_reasonably_low_error()
    test_evaluate_rejects_too_few_rows()
    print("ok")
