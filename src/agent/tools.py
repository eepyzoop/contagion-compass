"""
Read-only tools the agent can call to look at surveillance data before
deciding whether to flag an anomaly. The agent must call submit_verdict to
render its final judgment -- that's how its decision gets structured for
decision_log.
"""

import pandas as pd
from sqlalchemy import text

from src.analysis.stats import add_period_index


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


TOOL_IMPLS = {"check_status": check_status, "get_history": get_history}

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
