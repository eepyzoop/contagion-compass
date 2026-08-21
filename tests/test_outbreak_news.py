"""
Checks src.agent.outbreak_news's loop control flow (same shape as
test_reviewer_loop.py: returns the structured assessment cleanly, recovers
via one nudge, fails safe on prose-only) and check_outbreak_news's
no-articles-found path. No real WHO API/DB/LLM calls.

Usage:
    python -m tests.test_outbreak_news
"""

from src.agent.outbreak_news import _run_extraction_loop, check_outbreak_news
from src.agent.provider import Turn
import src.agent.outbreak_news as outbreak_news


class FakeBackend:
    """Replays a scripted sequence of Turns instead of calling a real LLM."""

    def __init__(self, turns):
        self._turns = list(turns)

    def start(self, system_prompt, user_prompt, tools=None):
        return self._turns.pop(0)

    def nudge(self, text):
        return self._turns.pop(0)


def test_returns_submit_assessment_arguments():
    turns = [
        Turn(
            tool_calls=[
                {
                    "id": "submit_outbreak_assessment",
                    "name": "submit_outbreak_assessment",
                    "arguments": {
                        "outbreak_confirmed": True,
                        "severity": "medium",
                        "reported_date": "2024-03-13",
                        "summary": "WHO confirmed a dengue outbreak in Brazil.",
                    },
                }
            ]
        )
    ]
    backend = FakeBackend(turns)
    assessment = _run_extraction_loop(backend, user_prompt="summarize these bulletins")
    assert assessment["outbreak_confirmed"] is True
    assert assessment["severity"] == "medium"


def test_nudge_recovers_assessment_after_prose_response():
    turns = [
        Turn(text="Let me think about this..."),
        Turn(
            tool_calls=[
                {
                    "id": "submit_outbreak_assessment",
                    "name": "submit_outbreak_assessment",
                    "arguments": {
                        "outbreak_confirmed": False,
                        "severity": "low",
                        "reported_date": "2024-03-13",
                        "summary": "No active outbreak reported.",
                    },
                }
            ]
        ),
    ]
    backend = FakeBackend(turns)
    assessment = _run_extraction_loop(backend, user_prompt="summarize these bulletins")
    assert assessment["outbreak_confirmed"] is False


def test_fails_safe_with_no_assessment_after_failed_nudge():
    turns = [Turn(text="Not sure..."), Turn(text="Still thinking...")]
    backend = FakeBackend(turns)
    assessment = _run_extraction_loop(backend, user_prompt="summarize these bulletins")
    assert assessment["outbreak_confirmed"] is None
    assert assessment["summary"]


def test_check_outbreak_news_returns_error_when_no_articles(monkeypatch):
    monkeypatch.setattr(outbreak_news, "fetch_recent_don", lambda disease, region, limit=3: [])
    result = check_outbreak_news(engine=None, region="NOWHERE")
    assert "error" in result


if __name__ == "__main__":
    class _Monkeypatch:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    test_returns_submit_assessment_arguments()
    test_nudge_recovers_assessment_after_prose_response()
    test_fails_safe_with_no_assessment_after_failed_nudge()
    test_check_outbreak_news_returns_error_when_no_articles(_Monkeypatch())
    print("ok")
