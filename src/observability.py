"""
Phase 7 task 3: optional Sentry error/warning tracking. Same blank-env-var-
means-skip pattern as S3_BUCKET/SLACK_WEBHOOK_URL -- init_sentry() no-ops
without SENTRY_DSN set, so this stays free/optional for local dev.
"""

import os

import sentry_sdk


def init_sentry() -> bool:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("ENV", "development"),
        traces_sample_rate=0.0,  # error/warning capture only, no perf tracing needed
    )
    return True
