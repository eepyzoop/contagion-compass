"""
Checks src.report.render()'s Markdown output includes the key facts a
reader needs (verdict, numbers, reasoning) -- pure string building, no
DB/LLM/filesystem involved.

Usage:
    python -m tests.test_report
"""

from src.report import render

RESULT = {
    "flagged": True,
    "confidence": "high",
    "reasoning": "Sustained rise well above the historical baseline.",
    "tool_calls_made": 3,
    "llm_provider": "ollama",
}

STATUS = {
    "period_start": "2026-06-28",
    "period_index": 26,
    "value": 900.0,
    "baseline_mean": 376.4,
    "baseline_stddev": 120.0,
    "n_baseline_years": 5,
    "z_score": 4.36,
}


def test_render_includes_verdict_and_numbers():
    md = render("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT, STATUS)
    assert "FLAGGED" in md
    assert "high" in md
    assert "900.0" in md
    assert "4.36" in md
    assert RESULT["reasoning"] in md
    assert "3 tool call(s)" in md


def test_render_not_flagged_says_so():
    result = {**RESULT, "flagged": False}
    md = render("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", result, STATUS)
    assert "Not flagged" in md
    assert "FLAGGED" not in md


if __name__ == "__main__":
    test_render_includes_verdict_and_numbers()
    test_render_not_flagged_says_so()
    print("ok")
