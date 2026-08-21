"""
Phase 2b agent loop: given a disease/region/metric, the LLM calls tools to
inspect the current reading vs. baseline (and, if it wants, a longer history
window) before rendering a judgment via submit_verdict. Every run writes one
row to decision_log -- flagged or not -- as the explainability audit trail.
"""

import pandas as pd
import sentry_sdk
from sqlalchemy import text

from src.agent.provider import get_backend
from src.agent.tools import TOOL_IMPLS, check_status
from src.analysis.stats import add_period_index
from src.db.connection import get_engine, init_schema

MAX_TOOL_CALLS = 5

SYSTEM_PROMPT = (
    "You are a public health surveillance analyst. You are given a "
    "disease/region/metric to review for this week. Use the tools available "
    "to check the current reading against its historical baseline, and "
    "optionally a longer history window if a single comparison isn't enough "
    "to judge. If the reading looks anomalous, investigate further before "
    "deciding: check_forecast gives you a trained model's expected value and "
    "range based on the recent trend, independent of the same-week baseline -- "
    "useful when the baseline and the trend might disagree (e.g. an "
    "outbreak building gradually); check_climate_and_alert gives you a "
    "second, independently-computed signal (InfoDengue's own alert level "
    "and Rt) plus a possible climate explanation for the same region; "
    "check_other_cities tells you whether the spike is isolated to this "
    "region or part of a broader regional pattern; check_outbreak_news "
    "checks WHO's official Disease Outbreak News bulletins for real-world "
    "corroboration -- useful for confirming a spike is a known reported "
    "outbreak, or noting that WHO hasn't flagged anything despite the "
    "numbers. You don't need any of these for a normal-looking reading. "
    "Decide whether this is a meaningful anomaly worth flagging to a human, "
    "or normal seasonal variation / a plausible mundane explanation (e.g. a "
    "holiday reporting lag). As a rough statistical reference (not a hard "
    "rule -- use judgment, especially around context like reporting lags or "
    "known outbreaks): z-scores under ~1.5 in magnitude are typically "
    "normal variation, and z-scores at or above ~2.5 in magnitude are "
    "typically the ones worth flagging. You MUST call the submit_verdict "
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
         reasoning, tool_calls_made, llm_provider,
         period_start, value, baseline_mean, baseline_stddev, z_score)
    VALUES
        (:disease, :region, :metric, :period_index, :flagged, :confidence,
         :reasoning, :tool_calls_made, :llm_provider,
         :period_start, :value, :baseline_mean, :baseline_stddev, :z_score)
    RETURNING id
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


def _run_loop(
    backend, engine, user_prompt: str, tool_impls: dict | None = None, tools: list | None = None
) -> tuple[dict, int]:
    """Drives the tool-call loop until submit_verdict or the budget runs out.
    Returns (verdict_dict, tool_calls_made). Isolated from the DB writes in
    `review()` so it can be exercised without a real Postgres connection.
    tool_impls/tools default to the real production tool set (TOOL_IMPLS/
    TOOL_SCHEMAS) -- scripts/evaluate_agent.py overrides both to replay
    historical weeks against a point-in-time-correct subset instead."""
    tool_impls = TOOL_IMPLS if tool_impls is None else tool_impls
    turn = backend.start(SYSTEM_PROMPT, user_prompt, tools=tools)

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
            sentry_sdk.add_breadcrumb(category="tool_call", message=call["name"], data=call["arguments"], level="info")
            impl = tool_impls.get(call["name"])
            if impl is None:
                result = {"error": f"unknown tool {call['name']}"}
            else:
                try:
                    result = impl(engine, **call["arguments"])
                except Exception as exc:  # noqa: BLE001 -- a flaky external call (e.g. WHO's API)
                    # shouldn't crash the whole run; give the model an error to react to instead.
                    sentry_sdk.capture_exception(exc)
                    result = {"error": f"{call['name']} failed: {exc}"}
            turn = backend.send_tool_result(call["id"], call["name"], result)
        nudged = False

    if verdict is None:
        # ponytail: tool-call budget exhausted without a verdict -- fail safe
        # by flagging for human review rather than silently dropping the run.
        sentry_sdk.capture_message(
            f"Agent exhausted tool-call budget ({MAX_TOOL_CALLS}) without a verdict", level="warning"
        )
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
    sentry_sdk.set_tag("llm_provider", backend.name)

    user_prompt = f"Review this week's data for disease={disease}, region={region}, metric={metric}."
    verdict, tool_calls_made = _run_loop(backend, engine, user_prompt)

    period_index = _current_period_index(engine, disease, region, metric)
    # A second, cheap check_status() call so decision_log stores the actual
    # numbers behind the verdict, not just the verdict text -- previously
    # only captured in the S3 manifest, not the DB itself. {"error": ...}
    # (no baseline yet) degrades to NULLs rather than blocking the insert;
    # period_index above already comes from raw_readings independently of
    # whether a baseline exists.
    status = check_status(engine, disease, region, metric)

    with engine.begin() as conn:
        decision_log_id = conn.execute(
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
                "period_start": status.get("period_start"),
                "value": status.get("value"),
                "baseline_mean": status.get("baseline_mean"),
                "baseline_stddev": status.get("baseline_stddev"),
                "z_score": status.get("z_score"),
            },
        ).scalar_one()

    return {
        "flagged": bool(verdict["flagged"]),
        "confidence": verdict["confidence"],
        "reasoning": verdict["reasoning"],
        "period_index": period_index,
        "tool_calls_made": tool_calls_made,
        "llm_provider": backend.name,
        "decision_log_id": decision_log_id,
    }
