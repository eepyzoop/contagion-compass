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
from sqlalchemy import text

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPORTS_DIR = "reports"
S3_BUCKET = os.environ.get("S3_BUCKET")

UPDATE_ARTIFACT_KEYS_SQL = text(
    """
    UPDATE decision_log
    SET report_key = :report_key, report_key_public = :report_key_public, chart_key = :chart_key
    WHERE id = :decision_log_id
    """
)


AUDIENCES = ("policymaker", "general_public")


def _friendly_region(region: str) -> str:
    return region.replace("-", ", ").replace("_", " ").title()


def render(
    disease: str,
    region: str,
    metric: str,
    result: dict,
    status: dict,
    chart_filename: str | None = None,
    opinion: dict | None = None,
    audience: str = "policymaker",
) -> str:
    """result: output of src.agent.reasoner.review(). status: output of
    src.agent.tools.check_status() for the same disease/region/metric --
    reused rather than requeried, since review() already looked it up.
    opinion: output of src.agent.reviewer.review(), if a second opinion
    was gathered. audience: "policymaker" (numbers-first, technical) or
    "general_public" (plain-language headline first, technical detail
    still included but clearly labeled, not hidden)."""
    if audience == "general_public":
        return _render_general_public(disease, region, metric, result, status, chart_filename, opinion)
    return _render_policymaker(disease, region, metric, result, status, chart_filename, opinion)


def _render_policymaker(disease, region, metric, result, status, chart_filename, opinion) -> str:
    verdict = "FLAGGED" if result["flagged"] else "Not flagged"
    lines = [
        f"# Surveillance report: {disease} / {region} / {metric}",
        "",
        f"**Period:** week of {status.get('period_start', 'unknown')} "
        f"(ISO week {status.get('period_index', '?')})",
        f"**Verdict:** {verdict} (confidence: {result['confidence']})",
        f"**Recommended action:** {_recommended_action(result)}",
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
        lines += ["", "## Second opinion", "", _opinion_line(opinion), "", opinion.get("notes", "")]
    lines += [
        "",
        "---",
        f"*Investigated with {result['tool_calls_made']} tool call(s), "
        f"via {result['llm_provider']}.*",
    ]
    return "\n".join(lines) + "\n"


def _render_general_public(disease, region, metric, result, status, chart_filename, opinion) -> str:
    flagged = result["flagged"]
    value, mean = status.get("value"), status.get("baseline_mean")
    if value is None or mean is None:
        comparison = "compared to what's typical"
    elif value > mean * 1.05:
        comparison = "higher than what's typically seen this time of year"
    elif value < mean * 0.95:
        comparison = "lower than what's typically seen this time of year"
    else:
        comparison = "about in line with what's typically seen this time of year"

    lines = [
        f"# {disease.title()} update: {_friendly_region(region)}",
        "",
        f"*Week of {status.get('period_start', 'unknown')}*",
        "",
        "**Bottom line:** "
        + ("Something worth a closer look this week." if flagged else "Nothing unusual to report this week."),
        "",
        f"This week, surveillance recorded about {value if value is not None else 'n/a'} "
        f"{metric.replace('_', ' ')}. That's {comparison}, based on "
        f"{status.get('n_baseline_years', 'several')} years of past data.",
        "",
        (
            "A public health analyst reviewed this reading and flagged it for a closer look."
            if flagged
            else "An automated review looked at this reading and found no cause for concern."
        ),
    ]
    if opinion is not None and opinion.get("agree") is False:
        lines += ["", "A second, independent review reached a different conclusion, so this is still being sorted out."]
    if chart_filename:
        lines += ["", f"![trend chart]({chart_filename})"]
    lines += [
        "",
        "---",
        "*Why the system decided this (technical notes):*",
        "",
        result["reasoning"],
    ]
    if opinion is not None:
        lines += ["", f"*Second opinion: {_opinion_line(opinion)}* {opinion.get('notes', '')}"]
    lines += [
        "",
        "---",
        "*This is an automated weekly surveillance update, not medical advice. "
        f"Investigated with {result['tool_calls_made']} tool call(s), via {result['llm_provider']}.*",
    ]
    return "\n".join(lines) + "\n"


def _opinion_line(opinion: dict) -> str:
    agree = opinion.get("agree")
    agree_text = "Agrees" if agree else "Disagrees" if agree is False else "No opinion returned"
    return f"**{agree_text}** with the verdict above (via {opinion.get('llm_provider', 'unknown')})."


def _recommended_action(result: dict) -> str:
    if not result["flagged"]:
        return "No action required; continue routine monitoring."
    if result["confidence"] == "high":
        return "Escalate to regional health authority for review."
    return "Monitor closely; consider requesting additional local reporting."


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
) -> tuple[dict[str, str], str | None]:
    """Writes both audience styles of the rendered report (and a shared trend
    chart, if history is given) to reports/. Returns
    ({"policymaker": path, "general_public": path}, chart_path_or_None)."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{disease}_{region}_{metric}_{stamp}"

    chart_path = None
    chart_filename = None
    if history:
        chart_filename = f"{base}.png"
        chart_path = os.path.join(REPORTS_DIR, chart_filename)
        _save_chart(chart_path, disease, region, metric, history, result["flagged"])

    report_paths = {}
    for audience in AUDIENCES:
        path = os.path.join(REPORTS_DIR, f"{base}_{audience}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(render(disease, region, metric, result, status, chart_filename, opinion, audience=audience))
        report_paths[audience] = path
    return report_paths, chart_path


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
    report_paths: dict[str, str],
    chart_path: str | None = None,
    opinion: dict | None = None,
    engine=None,
) -> str | None:
    """Writes a JSON summary of this run to S3 alongside the reports/chart
    (kept for the report/chart artifacts themselves -- see the 2026-08-21
    dashboard-data-source decision for why S3 stays just for files while
    structured run data moved to the /runs API). report_paths:
    {"policymaker": path, "general_public": path}, from save(). No-ops
    (returns None) if S3_BUCKET isn't set, same as upload_to_s3().
    If `engine` is given and result["decision_log_id"] is present, also
    writes the same report_key/report_key_public/chart_key back onto that
    decision_log row, so the /runs API can serve them to the dashboard."""
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
        "report_key": f"reports/{os.path.basename(report_paths['policymaker'])}",
        "report_key_public": f"reports/{os.path.basename(report_paths['general_public'])}",
        "chart_key": f"reports/{os.path.basename(chart_path)}" if chart_path else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base_name = os.path.splitext(os.path.basename(report_paths["policymaker"]))[0]
    base = base_name.removesuffix("_policymaker")
    key = f"reports/{base}.json"
    boto3.client("s3").put_object(
        Bucket=S3_BUCKET, Key=key, Body=json.dumps(manifest).encode(), ContentType="application/json"
    )

    if engine is not None and result.get("decision_log_id") is not None:
        with engine.begin() as conn:
            conn.execute(
                UPDATE_ARTIFACT_KEYS_SQL,
                {
                    "report_key": manifest["report_key"],
                    "report_key_public": manifest["report_key_public"],
                    "chart_key": manifest["chart_key"],
                    "decision_log_id": result["decision_log_id"],
                },
            )

    return f"s3://{S3_BUCKET}/{key}"
