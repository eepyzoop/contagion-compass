"""
Phase 7 task 5: agent evaluation harness. Replays historical weeks for a
disease/region/metric through the real agent loop (reasoner._run_loop,
reused directly rather than reimplemented) and compares its flagged/
not-flagged verdict against the naive |z| >= threshold rule already used
elsewhere in this project (src.analysis.stats). Reports an agreement rate
and dumps the agent's reasoning wherever the two diverge.

# ponytail: there's no ground-truth "was this an actual outbreak" label in
# this dataset, so "agreement with the naive z-score threshold" is the only
# metric available here -- it measures whether the LLM's judgment tracks
# the existing statistical convention, not whether either one is *correct*
# against real-world outcomes. A genuine precision/recall evaluation would
# need labeled ground truth (e.g. cross-referenced against WHO Disease
# Outbreak News bulletins confirming an actual outbreak per flagged week,
# now that check_outbreak_news exists) -- worth revisiting once there's
# enough history to mine, not built here.

Only check_status and get_history are available to the agent during
replay. check_forecast/check_climate_and_alert/check_other_cities/
check_outbreak_news all reflect *today's* live state (current Prophet fit,
today's climate, today's other-city snapshot, today's WHO bulletins) --
handing them to the agent while it judges a 2019 reading would be actively
wrong, not historically faithful. So this evaluates the agent's core
judgment against baseline+history, not its full investigative toolset.

Results persist to evaluation/ as JSON (gitignored, like reports/ and
data/raw/ -- regenerate by rerunning) so they're re-readable without
re-running the LLM, which is slow and can hit free-tier rate limits.

Usage:
    python -m scripts.evaluate_agent
    python -m scripts.evaluate_agent --weeks 10
    python -m scripts.evaluate_agent --disease dengue --region BRAZIL --metric reported_cases --weeks 20
"""

import argparse
import json
import os
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from src.agent.provider import get_backend
from src.agent.reasoner import _run_loop
from src.agent.tools import TOOL_SCHEMAS
from src.analysis.stats import DEFAULT_Z_THRESHOLD, add_period_index, compute_trailing_baseline
from src.db.connection import get_engine
from src.ingest.download_infodengue import DISEASE, METRIC, REGION

RESULTS_DIR = "evaluation"

REPLAY_TOOL_NAMES = {"check_status", "get_history", "submit_verdict"}
REPLAY_TOOL_SCHEMAS = [s for s in TOOL_SCHEMAS if s["function"]["name"] in REPLAY_TOOL_NAMES]


def _replay_tool_impls(history: pd.DataFrame, row_pos: int) -> dict:
    """check_status/get_history implementations scoped to exactly the data
    available as of the row at row_pos -- nothing later, no leakage."""
    visible = history.iloc[: row_pos + 1]
    current = history.iloc[row_pos]

    def check_status(engine, disease, region, metric):
        z = current["z_score"]
        return {
            "period_start": str(current["period_start"]),
            "period_index": int(current["period_index"]),
            "value": float(current["value"]),
            "baseline_mean": float(current["baseline_mean"]),
            "baseline_stddev": float(current["baseline_stddev"]),
            "n_baseline_years": int(current["n_baseline_years"]),
            "z_score": round(float(z), 2) if pd.notna(z) else None,
        }

    def get_history(engine, disease, region, metric, limit=12):
        tail = visible.tail(limit)
        return {"readings": [{"period_start": str(r.period_start), "value": float(r.value)} for r in tail.itertuples()]}

    return {"check_status": check_status, "get_history": get_history}


def evaluate(disease: str, region: str, metric: str, weeks: int) -> dict:
    engine = get_engine()
    readings = pd.read_sql(
        text(
            "SELECT period_start, value FROM raw_readings "
            "WHERE disease = :disease AND region = :region AND metric = :metric ORDER BY period_start"
        ),
        engine,
        params={"disease": disease, "region": region, "metric": metric},
    )
    readings = add_period_index(readings, date_col="period_start")
    # group_cols=() -- the SQL above already filtered to a single disease/
    # region/metric, so there's only one group; those columns were never
    # selected into `readings` in the first place.
    history = compute_trailing_baseline(readings, group_cols=()).dropna(subset=["z_score"]).reset_index(drop=True)
    if history.empty:
        raise SystemExit(f"No rows with enough trailing history for {disease}/{region}/{metric}.")

    sample_positions = history.tail(weeks).index  # most recent `weeks` rows with a valid baseline

    runs = []
    for pos in sample_positions:
        row = history.iloc[pos]
        naive_flagged = bool(abs(row["z_score"]) >= DEFAULT_Z_THRESHOLD)

        backend = get_backend()
        user_prompt = f"Review this week's data for disease={disease}, region={region}, metric={metric}."
        verdict, tool_calls_made = _run_loop(
            backend,
            engine,
            user_prompt,
            tool_impls=_replay_tool_impls(history, pos),
            tools=REPLAY_TOOL_SCHEMAS,
        )
        agent_flagged = bool(verdict["flagged"])
        agree = naive_flagged == agent_flagged

        runs.append(
            {
                "period_start": str(row["period_start"]),
                "z_score": round(float(row["z_score"]), 2),
                "naive_flagged": naive_flagged,
                "agent_flagged": agent_flagged,
                "agree": agree,
                "confidence": verdict.get("confidence"),
                "reasoning": verdict.get("reasoning"),
                "llm_provider": backend.name,
                "tool_calls_made": tool_calls_made,
            }
        )
        print(
            f"  {row['period_start']}  z={row['z_score']:+.2f}  naive={naive_flagged}  "
            f"agent={agent_flagged}  [{'agree' if agree else 'DIVERGE'}]"
        )

    agreement_rate = sum(r["agree"] for r in runs) / len(runs)
    return {
        "disease": disease,
        "region": region,
        "metric": metric,
        "weeks_evaluated": len(runs),
        "agreement_rate": round(agreement_rate, 3),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
    }


def _save(result: dict) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(RESULTS_DIR, f"eval_{result['disease']}_{result['region']}_{result['metric']}_{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disease", default=DISEASE)
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--metric", default=METRIC)
    parser.add_argument("--weeks", type=int, default=25, help="How many recent weeks (with a valid baseline) to replay.")
    args = parser.parse_args()

    print(f"Evaluating {args.disease}/{args.region}/{args.metric} over the last {args.weeks} weeks...")
    result = evaluate(args.disease, args.region, args.metric, args.weeks)

    print(f"\nAgreement rate: {result['agreement_rate']:.1%} ({result['weeks_evaluated']} weeks)")
    diverged = [r for r in result["runs"] if not r["agree"]]
    if diverged:
        print(f"\n{len(diverged)} divergence(s) -- agent's reasoning:")
        for r in diverged:
            print(
                f"\n  {r['period_start']}  z={r['z_score']:+.2f}  naive={r['naive_flagged']}  "
                f"agent={r['agent_flagged']} (via {r['llm_provider']})"
            )
            print(f"    {r['reasoning']}")

    path = _save(result)
    print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()
