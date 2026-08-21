"""
Phase 7 task 4: event-based surveillance corroboration. Given a region,
pulls recent WHO Disease Outbreak News bulletins mentioning it and asks an
LLM to extract a structured assessment -- this corroborates or explains
away a statistical anomaly with real-world outbreak reporting, distinct
from check_forecast/check_climate_and_alert's statistical/climate signals.

No API key needed -- WHO's DON API (src/ingest/who_don.py) is public and
unauthenticated, so this doesn't need the blank-env-var-means-skip pattern
used elsewhere for optional integrations; it degrades to {"error": ...} only
when WHO simply hasn't published anything matching, not from missing config.
"""

from src.ingest.download_infodengue import DISEASE
from src.ingest.who_don import fetch_recent_don

SYSTEM_PROMPT = (
    "You are a public health analyst summarizing WHO Disease Outbreak News "
    "bulletins. You'll be given one or more recent WHO bulletins about a "
    "disease/region. Extract a structured assessment: whether they describe "
    "a confirmed active outbreak, its severity, and a brief summary. You "
    "MUST call submit_outbreak_assessment exactly once -- never describe "
    "your assessment in plain text instead of calling it."
)

NUDGE_PROMPT = "Call the submit_outbreak_assessment tool now. Do not describe it in text -- invoke the tool."

ASSESSMENT_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "submit_outbreak_assessment",
            "description": "Submit your structured assessment of the WHO bulletins provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "outbreak_confirmed": {
                        "type": "boolean",
                        "description": "True if the bulletins describe a confirmed active outbreak, false otherwise.",
                    },
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "reported_date": {
                        "type": "string",
                        "description": "Publication date of the most relevant bulletin (YYYY-MM-DD).",
                    },
                    "summary": {"type": "string", "description": "Brief plain-English summary of what WHO reported."},
                },
                "required": ["outbreak_confirmed", "severity", "reported_date", "summary"],
            },
        },
    }
]


def _run_extraction_loop(backend, user_prompt: str) -> dict:
    turn = backend.start(SYSTEM_PROMPT, user_prompt, tools=ASSESSMENT_TOOL_SCHEMAS)
    if not turn.tool_calls:
        turn = backend.nudge(NUDGE_PROMPT)

    for call in turn.tool_calls:
        if call["name"] == "submit_outbreak_assessment":
            return call["arguments"]

    # ponytail: give up after one nudge, same fail-safe posture as reviewer.py --
    # a missing assessment shouldn't crash the run, just returns an unclear result.
    return {
        "outbreak_confirmed": None,
        "severity": None,
        "reported_date": None,
        "summary": (turn.text or "").strip() or "LLM did not return a structured assessment.",
    }


def check_outbreak_news(engine, region: str, disease: str = DISEASE) -> dict:
    """Live WHO Disease Outbreak News check for a region. `engine` is unused
    -- kept only so this matches the other tools.py functions' signature,
    which reasoner._run_loop calls uniformly as impl(engine, **arguments)."""
    # Deferred import: tools.py (which provider.py imports TOOL_SCHEMAS from)
    # registers this function, so a module-level import here would cycle
    # back through provider -> tools -> outbreak_news -> provider.
    from src.agent.provider import get_backend

    articles = fetch_recent_don(disease, region)
    if not articles:
        return {"error": f"no WHO Disease Outbreak News found for disease={disease}, region={region}"}

    user_prompt = "Recent WHO Disease Outbreak News bulletins:\n\n" + "\n\n".join(
        f"Title: {a['title']}\nPublished: {a['published']}\nOverview: {a['overview']}\nAssessment: {a['assessment']}"
        for a in articles
    )
    assessment = _run_extraction_loop(get_backend(), user_prompt)
    assessment["source_urls"] = [a["url"] for a in articles]
    return assessment
