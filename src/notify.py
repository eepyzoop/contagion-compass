"""
Phase 4: Slack alert when the agent flags an anomaly. Skipped (returns
False) if SLACK_WEBHOOK_URL isn't set -- same "no cloud creds needed for
local dev" pattern as src.report's S3 upload.

Phase 7 task 6: alert deduplication -- an ongoing anomaly would otherwise
re-alert every single week the scheduled agent runs, even with nothing new
to say. Suppressed unless it's an escalation relative to the most recent
prior decision_log row within the window: a fresh not-flagged -> flagged
transition, or this run's confidence exceeding the prior run's.
"""

import os
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import text

from src.db.connection import get_engine

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
ALERT_DEDUP_WINDOW_DAYS = int(os.environ.get("ALERT_DEDUP_WINDOW_DAYS") or "7")

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}

PRIOR_RUN_SQL = text(
    """
    SELECT flagged, confidence FROM decision_log
    WHERE disease = :disease AND region = :region AND metric = :metric
      AND id != :exclude_id AND created_at >= :since
    ORDER BY created_at DESC LIMIT 1
    """
)


def _confidence_rank(level: str) -> int:
    return _CONFIDENCE_RANK.get(level, 0)


def _is_escalation(new_confidence: str, prior_flagged: bool | None, prior_confidence: str | None) -> bool:
    """True if this run is worth alerting on relative to the most recent
    prior run: no prior run in the window at all, the prior run wasn't
    flagged (a fresh transition into a flagged state), or this run's
    confidence exceeds the prior flagged run's."""
    if prior_flagged is None:
        return True
    if not prior_flagged:
        return True
    return _confidence_rank(new_confidence) > _confidence_rank(prior_confidence)


def _last_prior_run(engine, disease: str, region: str, metric: str, exclude_id) -> tuple:
    since = datetime.now(timezone.utc) - timedelta(days=ALERT_DEDUP_WINDOW_DAYS)
    with engine.connect() as conn:
        row = conn.execute(
            PRIOR_RUN_SQL,
            {"disease": disease, "region": region, "metric": metric, "exclude_id": exclude_id, "since": since},
        ).first()
    return (row.flagged, row.confidence) if row else (None, None)


def notify_slack(disease: str, region: str, metric: str, result: dict, report_path: str, engine=None) -> bool:
    """Posts to Slack only when flagged, a webhook is configured, and this
    run is an escalation relative to the most recent prior one (see module
    docstring). Returns True if sent."""
    if not SLACK_WEBHOOK_URL or not result["flagged"]:
        return False

    engine = engine or get_engine()
    prior_flagged, prior_confidence = _last_prior_run(engine, disease, region, metric, result.get("decision_log_id"))
    if not _is_escalation(result["confidence"], prior_flagged, prior_confidence):
        return False

    text_body = (
        f":rotating_light: *{disease} / {region} / {metric}* flagged "
        f"(confidence: {result['confidence']})\n"
        f"{result['reasoning']}\n"
        f"Report: {report_path}"
    )
    resp = requests.post(SLACK_WEBHOOK_URL, json={"text": text_body}, timeout=10)
    resp.raise_for_status()
    return True
