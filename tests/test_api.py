"""
Self-contained checks on src.api's pure logic -- no live DB/LLM, no HTTP
server started. Route handlers themselves are thin wrappers around
already-tested modules (src.agent.reasoner/reviewer/tools), so what's worth
unit-testing here is the one piece of actual logic living in api.py: the
{"error": ...} tool-dict -> HTTPException translation, and that RunRequest
defaults line up with the real InfoDengue Rio de Janeiro config.

Usage:
    python -m tests.test_api
"""

from fastapi import HTTPException

from src.api import RunRequest, _tool_result
from src.ingest.download_infodengue import DISEASE, METRIC, REGION


def test_tool_result_passes_through_normal_dict():
    result = {"value": 1.0, "z_score": 2.5}
    assert _tool_result(result) is result


def test_tool_result_raises_404_on_error_dict():
    try:
        _tool_result({"error": "no baseline stored for week 5"})
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "no baseline stored for week 5"
    else:
        raise AssertionError("expected HTTPException")


def test_run_request_defaults_match_infodengue_config():
    body = RunRequest()
    assert body.disease == DISEASE
    assert body.region == REGION
    assert body.metric == METRIC
    assert body.fetch_latest is True


if __name__ == "__main__":
    test_tool_result_passes_through_normal_dict()
    test_tool_result_raises_404_on_error_dict()
    test_run_request_defaults_match_infodengue_config()
    print("ok")
