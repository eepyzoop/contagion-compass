"""
Phase 6b: a real trained forecasting model (Prophet) as a second, model-backed
signal alongside the z-score baseline in src/analysis/stats.py. That baseline
compares "this week" to the same ISO week in prior years; Prophet instead
learns the trend + yearly seasonality directly from the whole series and
produces an expected value *and* a confidence interval for the period being
reviewed -- a different, complementary way of catching "this doesn't match
what the recent trend would predict."

Prophet ships a prebuilt cmdstan binary in its Windows/Linux wheels, so no
compiler toolchain is needed to install or run it.
"""

import numpy as np
import pandas as pd
from prophet import Prophet


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    """Prophet requires columns named exactly `ds` (date) and `y` (value)."""
    return df.rename(columns={"period_start": "ds", "value": "y"})[["ds", "y"]].assign(
        ds=lambda d: pd.to_datetime(d["ds"])
    )


def fit(df: pd.DataFrame) -> Prophet:
    model = Prophet(weekly_seasonality=False, yearly_seasonality=True)
    model.fit(_prep(df))
    return model


def predict_next(df: pd.DataFrame, periods: int = 1) -> pd.DataFrame:
    """Fits on all of `df` and forecasts `periods` weeks past its last date."""
    model = fit(df)
    future = model.make_future_dataframe(periods=periods, freq="7D")
    forecast = model.predict(future)
    forecast["yhat_lower"] = forecast["yhat_lower"].clip(lower=0)  # case counts can't go negative
    return forecast.tail(periods)[["ds", "yhat", "yhat_lower", "yhat_upper"]]


def evaluate(df: pd.DataFrame, test_weeks: int = 52) -> dict:
    """
    Train/test split on the tail `test_weeks` of `df` (sorted by date): fits
    on everything before the split, forecasts across the held-out weeks, and
    reports MAE/RMSE against what actually happened. This is the honest
    evaluation Phase 6b calls for -- not just eyeballing a chart.
    """
    df = df.sort_values("period_start").reset_index(drop=True)
    if len(df) <= test_weeks:
        raise ValueError(f"need more than {test_weeks} rows to hold out a test set, got {len(df)}")

    train, test = df.iloc[:-test_weeks], df.iloc[-test_weeks:]
    forecast = predict_next(train, periods=test_weeks)

    actual = test["value"].to_numpy()
    predicted = forecast["yhat"].to_numpy()
    errors = actual - predicted
    return {
        "mae": float(np.abs(errors).mean()),
        "rmse": float(np.sqrt((errors**2).mean())),
        "n_test_weeks": test_weeks,
    }
