"""
Phase 4: Slack alert when the agent flags an anomaly. Skipped (returns
False) if SLACK_WEBHOOK_URL isn't set -- same "no cloud creds needed for
local dev" pattern as src.report's S3 upload.
"""

import os

import requests

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")


def notify_slack(disease: str, region: str, metric: str, result: dict, report_path: str) -> bool:
    """Posts to Slack only when flagged and a webhook is configured. Returns True if sent."""
    if not SLACK_WEBHOOK_URL or not result["flagged"]:
        return False
    text = (
        f":rotating_light: *{disease} / {region} / {metric}* flagged "
        f"(confidence: {result['confidence']})\n"
        f"{result['reasoning']}\n"
        f"Report: {report_path}"
    )
    resp = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
    resp.raise_for_status()
    return True
