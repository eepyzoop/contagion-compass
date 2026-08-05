"""
Checks src.notify.notify_slack()'s gating logic (skip when not flagged or
no webhook configured, post when both are true) using a monkeypatched
requests.post -- no real network call.

Usage:
    python -m tests.test_notify
"""

import src.notify as notify

RESULT_FLAGGED = {"flagged": True, "confidence": "high", "reasoning": "Sustained rise."}
RESULT_NOT_FLAGGED = {"flagged": False, "confidence": "high", "reasoning": "Normal variation."}


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


def test_posts_when_flagged_and_webhook_set(monkeypatch):
    notify.SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/fake"
    calls = []
    monkeypatch.setattr(notify.requests, "post", lambda url, json, timeout: calls.append((url, json)) or FakeResponse())
    sent = notify.notify_slack("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT_FLAGGED, "reports/x.md")
    assert sent is True
    assert len(calls) == 1
    assert calls[0][0] == "https://hooks.slack.com/services/fake"
    assert "dengue" in calls[0][1]["text"]


class _FakeMonkeypatch:
    def setattr(self, obj, name, value):
        self._prev = (obj, name, getattr(obj, name))
        setattr(obj, name, value)

    def undo(self):
        obj, name, prev = self._prev
        setattr(obj, name, prev)


if __name__ == "__main__":
    test_skips_when_no_webhook_configured()
    test_skips_when_not_flagged()
    mp = _FakeMonkeypatch()
    test_posts_when_flagged_and_webhook_set(mp)
    mp.undo()
    print("ok")