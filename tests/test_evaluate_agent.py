"""
Checks scripts.evaluate_agent's _replay_tool_impls -- the piece that makes
historical replay possible: does check_status/get_history see only data up
to and including the row under test, with no leakage from later rows.
No DB/LLM calls.

Usage:
    python -m tests.test_evaluate_agent
"""

import pandas as pd

from scripts.evaluate_agent import _replay_tool_impls


def _history():
    return pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2020-01-06", "2020-01-13", "2020-01-20", "2020-01-27"]),
            "value": [10.0, 20.0, 30.0, 40.0],
            "period_index": [2, 3, 4, 5],
            "baseline_mean": [8.0, 9.0, 10.0, 11.0],
            "baseline_stddev": [2.0, 2.0, 2.0, 2.0],
            "n_baseline_years": [3, 3, 3, 3],
            "z_score": [1.0, 5.5, 10.0, 14.5],
        }
    )


def test_check_status_reflects_only_the_row_under_test():
    impls = _replay_tool_impls(_history(), row_pos=2)
    status = impls["check_status"](engine=None, disease="dengue", region="X", metric="cases")
    assert status["value"] == 30.0
    assert status["z_score"] == 10.0


def test_get_history_excludes_future_rows():
    impls = _replay_tool_impls(_history(), row_pos=2)
    history = impls["get_history"](engine=None, disease="dengue", region="X", metric="cases", limit=12)["readings"]
    assert len(history) == 3  # rows 0, 1, 2 -- not row 3
    assert history[-1]["value"] == 30.0
    assert all(r["value"] != 40.0 for r in history)


def test_get_history_respects_limit():
    impls = _replay_tool_impls(_history(), row_pos=3)
    history = impls["get_history"](engine=None, disease="dengue", region="X", metric="cases", limit=2)["readings"]
    assert len(history) == 2
    assert history[-1]["value"] == 40.0


if __name__ == "__main__":
    test_check_status_reflects_only_the_row_under_test()
    test_get_history_excludes_future_rows()
    test_get_history_respects_limit()
    print("ok")
