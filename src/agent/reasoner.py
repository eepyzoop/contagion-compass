"""
Phase 2b agent loop: given a disease/region/metric, the LLM calls tools to
inspect the current reading vs. baseline (and, if it wants, a longer history
window) before rendering a judgment via submit_verdict. Every run writes one
row to decision_log -- flagged or not -- as the explainability audit trail.
"""

import pandas as pd
from sqlalchemy import text

from src.agent.provider import get_backend
from src.agent.tools import TOOL_IMPLS
from src.analysis.stats import add_period_index
from src.db.connection import get_engine, init_schema

MAX_TOOL_CALLS = 5

SYSTEM_PROMPT = (
    "You are a public health surveillance analyst. You are given a "
    "disease/region/metric to review for this week. Use the tools available "
    "to check the current reading against its historical baseline, and "
    "optionally a longer history window if a single comparison isn't enough "
    "to judge. Decide whether this is a meaningful anomaly worth flagging to "
    "a human, or normal seasonal variation / a plausible mundane explanation "
    "(e.g. a holiday reporting lag). As a rough statistical reference (not a "
    "hard rule -- use judgment, especially around context like reporting "
    "lags or known outbreaks): z-scores under ~1.5 in magnitude are "
    "typically normal variation, and z-scores at or above ~2.5 in magnitude "
    "are typically the ones worth flagging. You MUST call the submit_verdict "
    "tool exactly once when you've decided -- never describe your verdict "
    "in plain text instead of calling it."
)

NUDGE_PROMPT = (
    "Call the submit_verdict tool now with your final decision. Do not "
    "describe it in text -- invoke the tool."
)

INSERT_LOG_SQL = text(
    """
    INSERT INTO decision_log
        (disease, region, metric, period_index, flagged, confidence,
         reasoning, tool_calls_made, llm_provider)
    VALUES
        (:disease, :region, :metric, :period_index, :flagged, :confidence,
         :reasoning, :tool_calls_made, :llm_provider)
    """
)


def _current_period_index(engine, disease, region, metric) -> int:
    reading = pd.read_sql(
        text(
            """
            SELECT period_start FROM raw_readings
            WHERE disease = :disease AND region = :region AND metric = :metric
            ORDER BY period_start DESC LIMIT 1
            """
        ),
        engine,
        params={"disease": disease, "region": region, "metric": metric},
    )
    reading = add_period_index(reading, date_col="period_start")
    return int(reading.iloc[0]["period_index"])


def _run_loop(backend, engine, user_prompt: str) -> tuple[dict, int]:
    """Drives the tool-call loop until submit_verdict or the budget runs out.
    Returns (verdict_dict, tool_calls_made). Isolated from the DB writes in
    `review()` so it can be exercised without a real Postgres connection."""
    turn = backend.start(SYSTEM_PROMPT, user_prompt)

    tool_calls_made = 0
    verdict = None
    nudged = False

    while tool_calls_made < MAX_TOOL_CALLS and verdict is None:
        if not turn.tool_calls:
            # Local models sometimes describe a tool call in prose instead of
            # actually invoking it. One corrective nudge before giving up.
            if nudged:
                break
            turn = backend.nudge(NUDGE_PROMPT)
            nudged = True
            continue

        for call in turn.tool_calls:
            tool_calls_made += 1
            if call["name"] == "submit_verdict":
                verdict = call["arguments"]
                break
            impl = TOOL_IMPLS.get(call["name"])
            result = impl(engine, **call["arguments"]) if impl else {"error": f"unknown tool {call['name']}"}
            turn = backend.send_tool_result(call["id"], call["name"], result)
        nudged = False

    if verdict is None:
        # ponytail: tool-call budget exhausted without a verdict -- fail safe
        # by flagging for human review rather than silently dropping the run.
        verdict = {
            "flagged": True,
            "confidence": "low",
            "reasoning": (turn.text or "").strip()
            or "Agent exhausted its tool-call budget without reaching a verdict; flagging for human review.",
        }

    return verdict, tool_calls_made


def review(disease: str, region: str, metric: str, engine=None, backend=None) -> dict:
    engine = engine or get_engine()
    init_schema(engine)
    backend = backend or get_backend()

    user_prompt = f"Review this week's data for disease={disease}, region={region}, metric={metric}."
    verdict, tool_calls_made = _run_loop(backend, engine, user_prompt)

    period_index = _current_period_index(engine, disease, region, metric)

    with engine.begin() as conn:
        conn.execute(
            INSERT_LOG_SQL,
            {
                "disease": disease,
                "region": region,
                "metric": metric,
                "period_index": period_index,
                "flagged": bool(verdict["flagged"]),
                "confidence": verdict["confidence"],
                "reasoning": verdict["reasoning"],
                "tool_calls_made": tool_calls_made,
                "llm_provider": backend.name,
            },
        )

    return {
        "flagged": bool(verdict["flagged"]),
        "confidence": verdict["confidence"],
        "reasoning": verdict["reasoning"],
        "period_index": period_index,
        "tool_calls_made": tool_calls_made,
        "llm_provider": backend.name,
    }
