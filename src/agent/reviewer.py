"""
Phase 6: a second LLM call that critiques the primary agent's verdict
before the report is finalized -- a basic second-opinion layer, not a
second investigation (it only sees the same summary data the primary
agent already looked at, no tool-investigation loop). Records
agreement + notes to decision_log; does NOT override the primary
verdict -- flipping the outcome based on a second opinion is a bigger
behavior change than "add a second opinion" and isn't done here.

Uses its own get_backend() call, independent of which provider the
primary agent used -- same reliability abstraction, just invoked again.
"""

from sqlalchemy import text

from src.agent.provider import get_backend

SYSTEM_PROMPT = (
    "You are a second-opinion reviewer for a public health surveillance "
    "verdict. You'll be given the data another analyst looked at and their "
    "conclusion. Based on the same data, decide whether you agree with "
    "their flagged/not-flagged verdict. You MUST call submit_review "
    "exactly once -- never describe your opinion in plain text instead of "
    "calling it."
)

NUDGE_PROMPT = "Call the submit_review tool now with your opinion. Do not describe it in text -- invoke the tool."

REVIEW_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "submit_review",
            "description": "Submit your agree/disagree opinion on the primary analyst's verdict.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agree": {"type": "boolean", "description": "True if you agree with the primary verdict."},
                    "notes": {
                        "type": "string",
                        "description": "Brief explanation for your opinion, referencing the data.",
                    },
                },
                "required": ["agree", "notes"],
            },
        },
    }
]

UPDATE_REVIEW_SQL = text(
    """
    UPDATE decision_log
    SET reviewer_agree = :agree, reviewer_notes = :notes, reviewer_provider = :provider
    WHERE id = :decision_log_id
    """
)


def _run_review_loop(backend, user_prompt: str) -> dict:
    turn = backend.start(SYSTEM_PROMPT, user_prompt, tools=REVIEW_TOOL_SCHEMAS)
    if not turn.tool_calls:
        turn = backend.nudge(NUDGE_PROMPT)

    for call in turn.tool_calls:
        if call["name"] == "submit_review":
            return call["arguments"]

    # ponytail: give up after one nudge, same fail-safe posture as reasoner.py --
    # a missing review shouldn't block the report, just leaves reviewer_agree NULL.
    return {"agree": None, "notes": (turn.text or "").strip() or "Reviewer did not return a structured opinion."}


def review(disease: str, region: str, metric: str, result: dict, status: dict, backend=None) -> dict:
    backend = backend or get_backend()
    user_prompt = (
        f"Disease={disease}, region={region}, metric={metric}. "
        f"Current value={status.get('value')}, baseline mean={status.get('baseline_mean')}, "
        f"baseline stddev={status.get('baseline_stddev')}, z-score={status.get('z_score')}. "
        f"Primary analyst's verdict: {'FLAGGED' if result['flagged'] else 'not flagged'} "
        f"(confidence: {result['confidence']}). Their reasoning: {result['reasoning']}"
    )
    opinion = _run_review_loop(backend, user_prompt)
    return {
        "agree": opinion.get("agree"),
        "notes": opinion.get("notes", ""),
        "llm_provider": backend.name,
    }


def save_review(engine, decision_log_id: int, opinion: dict) -> None:
    with engine.begin() as conn:
        conn.execute(
            UPDATE_REVIEW_SQL,
            {
                "agree": opinion["agree"],
                "notes": opinion["notes"],
                "provider": opinion["llm_provider"],
                "decision_log_id": decision_log_id,
            },
        )
