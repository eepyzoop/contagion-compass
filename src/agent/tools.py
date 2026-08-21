"""
Read-only tools the agent can call to look at surveillance data before
deciding whether to flag an anomaly. The agent must call submit_verdict to
render its final judgment -- that's how its decision gets structured for
decision_log.
"""

import pandas as pd
from sqlalchemy import text

from src.agent.outbreak_news import check_outbreak_news
from src.analysis.forecast import predict_next
from src.analysis.stats import add_period_index
from src.ingest.download_infodengue import REGION_GEOCODES, fetch_latest_week_raw

MIN_FORECAST_TRAINING_WEEKS = 104  # ~2 years, enough for Prophet to learn yearly seasonality


def check_status(engine, disease: str, region: str, metric: str) -> dict:
    """Latest reading for (disease, region, metric) vs. its stored baseline."""
    reading = pd.read_sql(
        text(
            """
            SELECT period_start, value FROM raw_readings
            WHERE disease = :disease AND region = :region AND metric = :metric
            ORDER BY period_start DESC LIMIT 1
            """
        ),
        engine,
        params={"disease": disease, "region": region, "metric": metric},
    )
    if reading.empty:
        return {"error": f"no readings found for {disease}/{region}/{metric}"}

    reading = add_period_index(reading, date_col="period_start")
    period_index = int(reading.iloc[0]["period_index"])
    value = float(reading.iloc[0]["value"])

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
            "disease": disease,
            "region": region,
            "metric": metric,
            "period_index": period_index,
        },
    )
    if baseline.empty:
        return {"error": f"no baseline stored for week {period_index}"}

    mean = float(baseline.iloc[0]["historical_mean"])
    std = float(baseline.iloc[0]["historical_stddev"])
    z_score = (value - mean) / std if std > 0 else None

    return {
        "period_start": str(reading.iloc[0]["period_start"]),
        "period_index": period_index,
        "value": value,
        "baseline_mean": mean,
        "baseline_stddev": std,
        "n_baseline_years": int(baseline.iloc[0]["n_observations"]),
        "z_score": round(z_score, 2) if z_score is not None else None,
    }


def get_history(engine, disease: str, region: str, metric: str, limit: int = 12) -> dict:
    """Most recent `limit` weekly readings, oldest first -- for checking a longer time window."""
    history = pd.read_sql(
        text(
            """
            SELECT period_start, value FROM raw_readings
            WHERE disease = :disease AND region = :region AND metric = :metric
            ORDER BY period_start DESC LIMIT :limit
            """
        ),
        engine,
        params={"disease": disease, "region": region, "metric": metric, "limit": limit},
    )
    history = history.sort_values("period_start")
    return {
        "readings": [
            {"period_start": str(r.period_start), "value": float(r.value)}
            for r in history.itertuples()
        ]
    }


def check_forecast(engine, disease: str, region: str, metric: str) -> dict:
    """Trained-model expected value for the current period, independent of
    the historical-same-week baseline: fits Prophet on every reading *before*
    the current one and forecasts forward, so this is a genuine out-of-sample
    prediction, not a fit that already includes the point being judged."""
    readings = pd.read_sql(
        text(
            """
            SELECT period_start, value FROM raw_readings
            WHERE disease = :disease AND region = :region AND metric = :metric
            ORDER BY period_start
            """
        ),
        engine,
        params={"disease": disease, "region": region, "metric": metric},
    )
    if len(readings) < MIN_FORECAST_TRAINING_WEEKS + 1:
        return {"error": f"not enough history to train a forecast (need {MIN_FORECAST_TRAINING_WEEKS + 1}+ weeks)"}

    train, current = readings.iloc[:-1], readings.iloc[-1]
    forecast = predict_next(train, periods=1).iloc[0]

    return {
        "period_start": str(current["period_start"]),
        "actual_value": float(current["value"]),
        "predicted_value": round(float(forecast["yhat"]), 1),
        "predicted_range": [round(float(forecast["yhat_lower"]), 1), round(float(forecast["yhat_upper"]), 1)],
    }


def check_climate_and_alert(engine, region: str) -> dict:
    """Live climate/Rt/InfoDengue-alert-level context for the region under
    review, for judging whether a spike has a plausible climate-driven
    explanation. Only supported for InfoDengue-backed regions."""
    geocode = REGION_GEOCODES.get(region)
    if geocode is None:
        return {"error": f"no InfoDengue geocode mapping for region {region}"}
    return fetch_latest_week_raw(geocode)


def check_other_cities(engine) -> dict:
    """Live latest-week snapshot for other major Brazilian cities InfoDengue
    covers, for judging whether an anomaly is isolated to one city or
    showing up more broadly."""
    return {region: fetch_latest_week_raw(geocode) for region, geocode in REGION_GEOCODES.items()}


TOOL_IMPLS = {
    "check_status": check_status,
    "get_history": get_history,
    "check_forecast": check_forecast,
    "check_climate_and_alert": check_climate_and_alert,
    "check_other_cities": check_other_cities,
    "check_outbreak_news": check_outbreak_news,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "check_status",
            "description": (
                "Get the latest reading for a disease/region/metric and compare "
                "it to its stored historical baseline (mean, stddev, z-score)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "disease": {"type": "string"},
                    "region": {"type": "string"},
                    "metric": {"type": "string"},
                },
                "required": ["disease", "region", "metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_history",
            "description": (
                "Get the most recent N weekly readings for a disease/region/metric, "
                "to check a longer time window before deciding."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "disease": {"type": "string"},
                    "region": {"type": "string"},
                    "metric": {"type": "string"},
                    "limit": {"type": "integer", "description": "How many recent weeks (default 12)."},
                },
                "required": ["disease", "region", "metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_forecast",
            "description": (
                "Get a trained forecasting model's expected value and confidence "
                "range for the current period, based on the trend/seasonality in "
                "prior weeks alone (not the same-week-in-past-years baseline "
                "check_status uses). A second, independent way to judge whether "
                "this reading is unexpected -- useful when you want a model-backed "
                "expected range, not just a historical average."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "disease": {"type": "string"},
                    "region": {"type": "string"},
                    "metric": {"type": "string"},
                },
                "required": ["disease", "region", "metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_climate_and_alert",
            "description": (
                "Get live climate (temperature, humidity), Rt, and InfoDengue's "
                "own alert level (1-4) for the region under review -- use this "
                "if a reading looks anomalous and you want a second, "
                "independently-computed signal or a plausible climate explanation."
            ),
            "parameters": {
                "type": "object",
                "properties": {"region": {"type": "string"}},
                "required": ["region"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_other_cities",
            "description": (
                "Get a live latest-week snapshot for other major Brazilian cities "
                "InfoDengue covers -- use this to check whether an anomaly is "
                "isolated to one region or part of a broader regional pattern."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_outbreak_news",
            "description": (
                "Check WHO Disease Outbreak News for recent official bulletins "
                "mentioning this region -- use this to corroborate a statistical "
                "spike with real-world outbreak reporting, or to note that WHO "
                "hasn't reported anything unusual despite the numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {"region": {"type": "string"}},
                "required": ["region"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_verdict",
            "description": (
                "Submit your final decision. Call this exactly once, after you've "
                "gathered enough information to judge whether this is a meaningful "
                "anomaly or normal variation with a mundane explanation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "flagged": {
                        "type": "boolean",
                        "description": "True if worth flagging to a human, false otherwise.",
                    },
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "reasoning": {
                        "type": "string",
                        "description": "Plain-English explanation referencing the data you looked at.",
                    },
                },
                "required": ["flagged", "confidence", "reasoning"],
            },
        },
    },
]
