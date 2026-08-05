"""
Checks src.report.render()'s Markdown output includes the key facts a
reader needs (verdict, numbers, reasoning) -- pure string building, no
DB/LLM/filesystem involved. Also checks save()'s chart generation writes
a real PNG when history is given.

Usage:
    python -m tests.test_report
"""

import os
import shutil
import tempfile

from src.report import render, save

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


def test_render_embeds_chart_when_given():
    md = render("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT, STATUS, chart_filename="x.png")
    assert "![trend chart](x.png)" in md


def test_render_omits_chart_when_absent():
    md = render("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT, STATUS)
    assert "![trend chart]" not in md


def test_save_writes_chart_when_history_given():
    tmpdir = tempfile.mkdtemp()
    prev_dir = os.getcwd()
    os.chdir(tmpdir)
    try:
        history = [{"period_start": f"2026-0{i}-01", "value": 100.0 + i} for i in range(1, 6)]
        report_path, chart_path = save(
            "dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT, STATUS, history=history
        )
        assert os.path.isfile(report_path)
        assert chart_path is not None and os.path.isfile(chart_path)
        assert os.path.basename(chart_path) in open(report_path).read()
    finally:
        os.chdir(prev_dir)
        shutil.rmtree(tmpdir)


def test_save_skips_chart_without_history():
    tmpdir = tempfile.mkdtemp()
    prev_dir = os.getcwd()
    os.chdir(tmpdir)
    try:
        report_path, chart_path = save("dengue", "BRAZIL-RIO_DE_JANEIRO", "estimated_cases", RESULT, STATUS)
        assert chart_path is None
    finally:
        os.chdir(prev_dir)
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    test_render_includes_verdict_and_numbers()
    test_render_not_flagged_says_so()
    test_render_embeds_chart_when_given()
    test_render_omits_chart_when_absent()
    test_save_writes_chart_when_history_given()
    test_save_skips_chart_without_history()
    print("ok")
