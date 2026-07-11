"""
Phase 4: turns one agent run into a plain-English Markdown report -- the
human-readable counterpart to the decision_log audit trail. `render()` is a
pure string-builder (no DB/LLM) so it's testable in isolation; `save()`
writes it to reports/, gitignored like data/raw since these regenerate.
"""

import os
from datetime import datetime, timezone

REPORTS_DIR = "reports"


def render(disease: str, region: str, metric: str, result: dict, status: dict) -> str:
    """result: output of src.agent.reasoner.review(). status: output of
    src.agent.tools.check_status() for the same disease/region/metric --
    reused rather than requeried, since review() already looked it up."""
    verdict = "FLAGGED" if result["flagged"] else "Not flagged"
    lines = [
        f"# Surveillance report: {disease} / {region} / {metric}",
        "",
        f"**Period:** week of {status.get('period_start', 'unknown')} "
        f"(ISO week {status.get('period_index', '?')})",
        f"**Verdict:** {verdict} (confidence: {result['confidence']})",
        "",
        "## Reading vs. baseline",
        "",
        f"- Current value: {status.get('value', 'n/a')}",
        f"- Historical mean: {status.get('baseline_mean', 'n/a')}",
        f"- Historical stddev: {status.get('baseline_stddev', 'n/a')}",
        f"- z-score: {status.get('z_score', 'n/a')}",
        f"- Baseline built from {status.get('n_baseline_years', '?')} years of data",
        "",
        "## Agent's reasoning",
        "",
        result["reasoning"],
        "",
        "---",
        f"*Investigated with {result['tool_calls_made']} tool call(s), "
        f"via {result['llm_provider']}.*",
    ]
    return "\n".join(lines) + "\n"


def save(disease: str, region: str, metric: str, result: dict, status: dict) -> str:
    """Writes the rendered report to reports/ and returns the file path."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{disease}_{region}_{metric}_{stamp}.md"
    path = os.path.join(REPORTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(disease, region, metric, result, status))
    return path
