"""
Checks src.notify.notify_slack()'s gating logic (skip when not flagged or
no webhook configured, post when both are true) and the Phase 7 task 6
dedup logic (_is_escalation, and notify_slack suppressing/allowing based on
it) -- all via monkeypatched requests.post/_last_prior_run, no real network
or DB call.

Usage:
    python -m tests.test_notify
"""

import src.notify as notify

RESULT_FLAGGED = {"flagged": True, "confidence": "high", "reasoning": "Sustained rise.", "decision_log_id": 99}
RESULT_NOT_FLAGGED = {"flagged": False, "confidence": "high", "reasoning": "Normal variation.", "decision_log_id": 99}


class FakeResponse:
    def raise_for_status(self):
        pass


def test_skips_when_no_webhook_configured():
    notify.SLACK_WEBHOOK_URL = None
    sent = notify.notify_slack("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT_FLAGGED, "reports/x.md")
    assert sent is False


def test_skips_when_not_flagged():
    notify.SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/fake"
    sent = notify.notify_slack(
        "dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT_NOT_FLAGGED, "reports/x.md"
    )
    assert sent is False


def test_posts_when_flagged_webhook_set_and_no_prior_run(monkeypatch):
    notify.SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/fake"
    monkeypatch.setattr(notify, "_last_prior_run", lambda *a, **k: (None, None))
    calls = []
    monkeypatch.setattr(notify.requests, "post", lambda url, json, timeout: calls.append((url, json)) or FakeResponse())
    sent = notify.notify_slack("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT_FLAGGED, "reports/x.md")
    assert sent is True
    assert len(calls) == 1
    assert calls[0][0] == "https://hooks.slack.com/services/fake"
    assert "dengue" in calls[0][1]["text"]


def test_suppresses_repeat_alert_at_same_confidence(monkeypatch):
    notify.SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/fake"
    monkeypatch.setattr(notify, "_last_prior_run", lambda *a, **k: (True, "high"))  # same rank as RESULT_FLAGGED
    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")))
    sent = notify.notify_slack("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT_FLAGGED, "reports/x.md")
    assert sent is False


def test_allows_alert_when_confidence_escalates(monkeypatch):
    notify.SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/fake"
    monkeypatch.setattr(notify, "_last_prior_run", lambda *a, **k: (True, "low"))  # RESULT_FLAGGED is "high" -- escalation
    calls = []
    monkeypatch.setattr(notify.requests, "post", lambda url, json, timeout: calls.append((url, json)) or FakeResponse())
    sent = notify.notify_slack("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT_FLAGGED, "reports/x.md")
    assert sent is True
    assert len(calls) == 1


def test_is_escalation_pure_logic():
    assert notify._is_escalation("low", None, None) is True  # no prior run at all
    assert notify._is_escalation("low", False, "high") is True  # not-flagged -> flagged
    assert notify._is_escalation("medium", True, "low") is True  # confidence increased
    assert notify._is_escalation("medium", True, "medium") is False  # same, suppress
    assert notify._is_escalation("low", True, "high") is False  # lower than prior, suppress


class _FakeMonkeypatch:
    def __init__(self):
        self._prev = []

    def setattr(self, obj, name, value):
        self._prev.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, prev in reversed(self._prev):
            setattr(obj, name, prev)
        self._prev = []


if __name__ == "__main__":
    test_skips_when_no_webhook_configured()
    test_skips_when_not_flagged()
    for fn in (
        test_posts_when_flagged_webhook_set_and_no_prior_run,
        test_suppresses_repeat_alert_at_same_confidence,
        test_allows_alert_when_confidence_escalates,
    ):
        mp = _FakeMonkeypatch()
        fn(mp)
        mp.undo()
    test_is_escalation_pure_logic()
    print("ok")
