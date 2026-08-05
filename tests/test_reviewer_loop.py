"""
Smallest possible check on the reviewer's loop control flow: does it
return the submit_review arguments cleanly, recover via one nudge if the
model responds with prose, and fail safe (agree=None, note explaining
why) if it still never calls submit_review. No DB/LLM calls.

Usage:
    python -m tests.test_reviewer_loop
"""

from src.agent.provider import Turn
from src.agent.reviewer import _run_review_loop


class FakeBackend:
    """Replays a scripted sequence of Turns instead of calling a real LLM."""

    def __init__(self, turns):
        self._turns = list(turns)

    def start(self, system_prompt, user_prompt, tools=None):
        return self._turns.pop(0)

    def nudge(self, text):
        return self._turns.pop(0)


def test_returns_submit_review_arguments():
    turns = [
        Turn(tool_calls=[{"id": "submit_review", "name": "submit_review", "arguments": {"agree": True, "notes": "checks out"}}])
    ]
    backend = FakeBackend(turns)
    opinion = _run_review_loop(backend, user_prompt="review this")
    assert opinion == {"agree": True, "notes": "checks out"}


def test_nudge_recovers_opinion_after_prose_response():
    turns = [
        Turn(text="I think this looks reasonable..."),
        Turn(tool_calls=[{"id": "submit_review", "name": "submit_review", "arguments": {"agree": False, "notes": "z-score is borderline"}}]),
    ]
    backend = FakeBackend(turns)
    opinion = _run_review_loop(backend, user_prompt="review this")
    assert opinion == {"agree": False, "notes": "z-score is borderline"}


def test_fails_safe_with_no_opinion_after_failed_nudge():
    turns = [
        Turn(text="Not sure..."),
        Turn(text="Still thinking..."),
    ]
    backend = FakeBackend(turns)
    opinion = _run_review_loop(backend, user_prompt="review this")
    assert opinion["agree"] is None
    assert opinion["notes"]


if __name__ == "__main__":
    test_returns_submit_review_arguments()
    test_nudge_recovers_opinion_after_prose_response()
    test_fails_safe_with_no_opinion_after_failed_nudge()
    print("ok")
