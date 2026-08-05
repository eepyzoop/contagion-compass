"""
Phase 2b entry point: pulls the latest InfoDengue week for Rio de Janeiro,
loads it, then hands the flag/don't-flag judgment to the LLM agent (Ollama
primary, Gemini fallback) instead of a bare z-score threshold. Every run
writes one row to decision_log -- the explainability audit trail.

Requires scripts/refresh_baseline_infodengue.py to have been run at least
once so a baseline exists to compare against.

Usage:
    python -m scripts.run_agent
"""

from src.agent import reviewer
from src.agent.reasoner import review
from src.agent.tools import check_status, get_history
from src.db.connection import get_engine
from src.db.load import load_readings
from src.ingest.download_infodengue import DISEASE, METRIC, REGION, fetch_latest_week
from src.notify import notify_slack
from src.report import save as save_report
from src.report import upload_manifest, upload_to_s3


def main():
    engine = get_engine()

    print("Fetching latest InfoDengue week for Rio de Janeiro...")
    latest = fetch_latest_week()
    row = latest.iloc[0]
    print(f"  {row['period_start']}: {row['value']:.1f} estimated cases")

    load_readings(latest)

    print("\nHanding off to the agent for judgment...")
    result = review(DISEASE, REGION, METRIC, engine=engine)

    print(f"\nProvider: {result['llm_provider']} | tool calls made: {result['tool_calls_made']}")
    print(f"Verdict: {'FLAGGED' if result['flagged'] else 'not flagged'} (confidence: {result['confidence']})")
    print(f"Reasoning: {result['reasoning']}")

    status = check_status(engine, DISEASE, REGION, METRIC)

    print("\nGetting a second opinion...")
    opinion = reviewer.review(DISEASE, REGION, METRIC, result, status)
    reviewer.save_review(engine, result["decision_log_id"], opinion)
    agree_text = "agrees" if opinion["agree"] else "disagrees" if opinion["agree"] is False else "no opinion"
    print(f"Reviewer ({opinion['llm_provider']}) {agree_text}: {opinion['notes']}")

    history = get_history(engine, DISEASE, REGION, METRIC)["readings"]
    report_path, chart_path = save_report(DISEASE, REGION, METRIC, result, status, history=history, opinion=opinion)
    print(f"\nReport saved: {report_path}")

    for path in (report_path, chart_path):
        if not path:
            continue
        s3_uri = upload_to_s3(path)
        if s3_uri:
            print(f"Uploaded to {s3_uri}")

    manifest_uri = upload_manifest(DISEASE, REGION, METRIC, result, status, report_path, chart_path, opinion=opinion)
    if manifest_uri:
        print(f"Uploaded to {manifest_uri}")

    if notify_slack(DISEASE, REGION, METRIC, result, report_path):
        print("Slack alert sent.")


if __name__ == "__main__":
    main()
