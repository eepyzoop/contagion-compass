"""
Phase 4: turns one agent run into a plain-English Markdown report -- the
human-readable counterpart to the decision_log audit trail. `render()` is a
pure string-builder (no DB/LLM) so it's testable in isolation; `save()`
writes it to reports/, gitignored like data/raw since these regenerate.
"""

import json
import os
from datetime import datetime, timezone

import boto3
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPORTS_DIR = "reports"
S3_BUCKET = os.environ.get("S3_BUCKET")


def render(
    disease: str,
    region: str,
    metric: str,
    result: dict,
    status: dict,
    chart_filename: str | None = None,
    opinion: dict | None = None,
) -> str:
    """result: output of src.agent.reasoner.review(). status: output of
    src.agent.tools.check_status() for the same disease/region/metric --
    reused rather than requeried, since review() already looked it up.
    opinion: output of src.agent.reviewer.review(), if a second opinion
    was gathered."""
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
    ]
    if chart_filename:
        lines += ["", f"![trend chart]({chart_filename})"]
    lines += [
        "",
        "## Agent's reasoning",
        "",
        result["reasoning"],
    ]
    if opinion is not None:
        agree = opinion.get("agree")
        agree_text = "Agrees" if agree else "Disagrees" if agree is False else "No opinion returned"
        lines += [
            "",
            "## Second opinion",
            "",
            f"**{agree_text}** with the verdict above (via {opinion.get('llm_provider', 'unknown')}).",
            "",
            opinion.get("notes", ""),
        ]
    lines += [
        "",
        "---",
        f"*Investigated with {result['tool_calls_made']} tool call(s), "
        f"via {result['llm_provider']}.*",
    ]
    return "\n".join(lines) + "\n"


def _save_chart(path: str, disease: str, region: str, metric: str, history: list[dict], flagged: bool) -> None:
    """history: [{period_start, value}, ...] oldest first, from get_history().
    Highlights the most recent point red if flagged, else the normal series color."""
    dates = [h["period_start"] for h in history]
    values = [h["value"] for h in history]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(dates, values, marker="o", color="tab:blue")
    if values:
        ax.plot(dates[-1], values[-1], marker="o", markersize=10, zorder=5, color="red" if flagged else "tab:blue")
    ax.set_title(f"{disease} / {region} / {metric}")
    ax.set_ylabel(metric)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def save(
    disease: str,
    region: str,
    metric: str,
    result: dict,
    status: dict,
    history: list[dict] | None = None,
    opinion: dict | None = None,
) -> tuple[str, str | None]:
    """Writes the rendered report (and a trend chart, if history is given) to
    reports/. Returns (report_path, chart_path_or_None)."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{disease}_{region}_{metric}_{stamp}"

    chart_path = None
    chart_filename = None
    if history:
        chart_filename = f"{base}.png"
        chart_path = os.path.join(REPORTS_DIR, chart_filename)
        _save_chart(chart_path, disease, region, metric, history, result["flagged"])

    report_path = os.path.join(REPORTS_DIR, f"{base}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(render(disease, region, metric, result, status, chart_filename, opinion))
    return report_path, chart_path


def upload_to_s3(path: str) -> str | None:
    """Uploads a saved report to S3 if S3_BUCKET is set; returns the s3:// URI,
    or None if S3 isn't configured (local-only dev stays free/no-AWS-required)."""
    if not S3_BUCKET:
        return None
    key = f"reports/{os.path.basename(path)}"
    boto3.client("s3").upload_file(path, S3_BUCKET, key)
    return f"s3://{S3_BUCKET}/{key}"


def upload_manifest(
    disease: str,
    region: str,
    metric: str,
    result: dict,
    status: dict,
    report_path: str,
    chart_path: str | None = None,
    opinion: dict | None = None,
) -> str | None:
    """Writes a JSON summary of this run to S3 alongside the report/chart --
    the dashboard's only data source, so it never needs direct DB access.
    No-ops (returns None) if S3_BUCKET isn't set, same as upload_to_s3()."""
    if not S3_BUCKET:
        return None
    manifest = {
        "disease": disease,
        "region": region,
        "metric": metric,
        "period_start": status.get("period_start"),
        "period_index": status.get("period_index"),
        "value": status.get("value"),
        "baseline_mean": status.get("baseline_mean"),
        "baseline_stddev": status.get("baseline_stddev"),
        "z_score": status.get("z_score"),
        "flagged": result["flagged"],
        "confidence": result["confidence"],
        "reasoning": result["reasoning"],
        "tool_calls_made": result["tool_calls_made"],
        "llm_provider": result["llm_provider"],
        "reviewer_agree": opinion.get("agree") if opinion else None,
        "reviewer_notes": opinion.get("notes") if opinion else None,
        "reviewer_provider": opinion.get("llm_provider") if opinion else None,
        "report_key": f"reports/{os.path.basename(report_path)}",
        "chart_key": f"reports/{os.path.basename(chart_path)}" if chart_path else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base = os.path.splitext(os.path.basename(report_path))[0]
    key = f"reports/{base}.json"
    boto3.client("s3").put_object(
        Bucket=S3_BUCKET, Key=key, Body=json.dumps(manifest).encode(), ContentType="application/json"
    )
    return f"s3://{S3_BUCKET}/{key}"
