"""
Smallest possible check on the agent's tool-call loop control flow: does it
stop cleanly on submit_verdict, recover via a nudge if the model responds
with prose instead of a tool call, and fail safe (flag for review) if it
still never calls submit_verdict within the budget. No DB/LLM calls.

Usage:
    python -m tests.test_reasoner_loop
"""

from src.agent.provider import Turn
from src.agent.reasoner import MAX_TOOL_CALLS, _run_loop


class FakeBackend:
    """Replays a scripted sequence of Turns instead of calling a real LLM."""

    def __init__(self, turns):
        self._turns = list(turns)

    def start(self, system_prompt, user_prompt, tools=None):
        return self._turns.pop(0)

    def send_tool_result(self, tool_call_id, name, result):
        return self._turns.pop(0)

    def nudge(self, text):
        return self._turns.pop(0)


def test_stops_on_submit_verdict():
    # Tool name deliberately isn't a real TOOL_IMPLS entry -- this test only
    # exercises loop control flow, not the real DB-backed tool functions.
    turns = [
        Turn(tool_calls=[{"id": "unscripted_tool", "name": "unscripted_tool", "arguments": {}}]),
        Turn(
            tool_calls=[
                {
                    "id": "submit_verdict",
                    "name": "submit_verdict",
                    "arguments": {"flagged": True, "confidence": "high", "reasoning": "z=9"},
                }
            ]
        ),
    ]
    backend = FakeBackend(turns)
    verdict, calls = _run_loop(backend, engine=None, user_prompt="review")
    assert verdict == {"flagged": True, "confidence": "high", "reasoning": "z=9"}
    assert calls == 2


def test_fails_safe_when_budget_exhausted():
    # Model keeps calling an (unscripted) tool forever and never submits a verdict.
    turns = [
        Turn(tool_calls=[{"id": "unscripted_tool", "name": "unscripted_tool", "arguments": {}}])
    ] * (MAX_TOOL_CALLS + 1)
    backend = FakeBackend(turns)
    verdict, calls = _run_loop(backend, engine=None, user_prompt="review")
    assert verdict["flagged"] is True
    assert verdict["confidence"] == "low"
    assert calls == MAX_TOOL_CALLS


def test_nudge_recovers_verdict_after_prose_response():
    # Model responds with prose instead of a tool call, then calls
    # submit_verdict once nudged.
    turns = [
        Turn(text="I think this looks fine but let me think it over..."),
        Turn(
            tool_calls=[
                {
                    "id": "submit_verdict",
                    "name": "submit_verdict",
                    "arguments": {"flagged": False, "confidence": "high", "reasoning": "normal"},
                }
            ]
        ),
    ]
    backend = FakeBackend(turns)
    verdict, calls = _run_loop(backend, engine=None, user_prompt="review")
    assert verdict == {"flagged": False, "confidence": "high", "reasoning": "normal"}
    assert calls == 1


def test_gives_up_after_one_failed_nudge():
    turns = [
        Turn(text="I'm not sure yet..."),
        Turn(text="Still thinking..."),
    ]
    backend = FakeBackend(turns)
    verdict, calls = _run_loop(backend, engine=None, user_prompt="review")
    assert verdict["flagged"] is True
    assert verdict["confidence"] == "low"
    assert calls == 0


if __name__ == "__main__":
    test_stops_on_submit_verdict()
    test_fails_safe_when_budget_exhausted()
    test_nudge_recovers_verdict_after_prose_response()
    test_gives_up_after_one_failed_nudge()
    print("ok")
