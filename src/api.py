"""
Phase 7 task 2: REST API with Swagger docs (/docs, /openapi.json) over the
agent/tools/report modules that already exist. Every route is a thin
wrapper -- no judgment logic lives here, it lives in src.agent.reasoner/
reviewer and src.agent.tools, same as scripts/run_agent.py already uses.

Run locally with:
    uvicorn src.api:app --reload --port 8000
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.agent import reviewer
from src.agent.reasoner import review as run_review
from src.agent.tools import check_forecast, check_status
from src.agent.tools import get_history as tool_get_history
from src.db.connection import get_engine, init_schema
from src.db.load import load_readings
from src.ingest.download_infodengue import DISEASE as DEFAULT_DISEASE
from src.ingest.download_infodengue import METRIC as DEFAULT_METRIC
from src.ingest.download_infodengue import REGION as DEFAULT_REGION
from src.ingest.download_infodengue import REGION_GEOCODES, fetch_latest_week
from src.observability import init_sentry

init_sentry()

engine = get_engine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Deferred to app startup (not module import) so `import src.api` alone
    # -- e.g. from tests -- doesn't require a live DB connection.
    init_schema(engine)
    yield


app = FastAPI(
    title="Contagion Compass API",
    description="Trigger agent-driven surveillance reviews, browse run history, and read the underlying data.",
    version="1.0.0",
    lifespan=lifespan,
)

_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- schemas --

class RunRequest(BaseModel):
    disease: str = Field(default=DEFAULT_DISEASE, description="Disease identifier.", examples=["dengue"])
    region: str = Field(default=DEFAULT_REGION, description="Region identifier.", examples=["BRAZIL-RIO_DE_JANEIRO"])
    metric: str = Field(default=DEFAULT_METRIC, description="Metric name.", examples=["estimated_cases"])
    fetch_latest: bool = Field(
        default=True,
        description=(
            "Fetch and load the latest InfoDengue week before reviewing. Only takes "
            "effect for the live-source region (BRAZIL-RIO_DE_JANEIRO) -- other "
            "regions are reviewed against whatever's already stored, since there's "
            "no live weekly source for them yet."
        ),
    )


class StatusResponse(BaseModel):
    period_start: str = Field(description="Start date of the reporting week.")
    period_index: int = Field(description="ISO week-of-year.")
    value: float = Field(description="Reported/estimated value for this period.")
    baseline_mean: float = Field(description="Historical mean for this week-of-year.")
    baseline_stddev: float = Field(description="Historical standard deviation for this week-of-year.")
    n_baseline_years: int = Field(description="How many years of history fed the baseline.")
    z_score: Optional[float] = Field(description="(value - mean) / stddev, null if stddev is 0.")


class ReviewerOpinion(BaseModel):
    agree: Optional[bool] = Field(description="True/False, or null if the reviewer never returned a structured opinion.")
    notes: str = Field(description="Reviewer's explanation.")
    llm_provider: str = Field(description="Which LLM backend produced this opinion.")


class RunResult(BaseModel):
    decision_log_id: int = Field(description="Row id in decision_log for this run.")
    disease: str
    region: str
    metric: str
    period_index: int = Field(description="ISO week-of-year reviewed.")
    flagged: bool = Field(description="Whether the primary agent flagged this as a meaningful anomaly.")
    confidence: str = Field(description="low | medium | high")
    reasoning: str = Field(description="Primary agent's plain-English reasoning.")
    tool_calls_made: int
    llm_provider: str = Field(description="Which LLM backend the primary agent used.")
    status: StatusResponse
    reviewer: ReviewerOpinion


class HistoryReading(BaseModel):
    period_start: str
    value: float


class HistoryResponse(BaseModel):
    readings: list[HistoryReading]


class ForecastResponse(BaseModel):
    period_start: str
    actual_value: float
    predicted_value: float = Field(description="Prophet's point forecast for this period.")
    predicted_range: list[float] = Field(description="[lower, upper] confidence interval, floored at 0.")


class DecisionLogEntry(BaseModel):
    id: int
    disease: str
    region: str
    metric: str
    period_index: int
    flagged: bool
    confidence: str
    reasoning: str
    tool_calls_made: int
    llm_provider: str
    reviewer_agree: Optional[bool]
    reviewer_notes: Optional[str]
    reviewer_provider: Optional[str]
    created_at: datetime


class RunsPage(BaseModel):
    total: int = Field(description="Total matching rows, ignoring limit/offset.")
    limit: int
    offset: int
    runs: list[DecisionLogEntry]


class RegionInfo(BaseModel):
    disease: str
    region: str
    metric: str
    has_baseline: bool = Field(description="Whether a stored baseline exists (required for review() to work).")
    live_climate_data: bool = Field(description="Whether check_climate_and_alert/check_other_cities cover this region.")


class HealthResponse(BaseModel):
    status: str
    database: str


# ------------------------------------------------------------------ helpers --

def _tool_result(result: dict) -> dict:
    """Tool functions (src.agent.tools) return {"error": ...} dicts on bad
    input rather than raising -- they're also called from inside the LLM
    loop, where an exception would just crash the run instead of giving the
    model something to react to. The API is what actually has HTTP
    semantics, so this is where that becomes a real 404."""
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


def _run_one(disease: str, region: str, metric: str, fetch_latest: bool) -> RunResult:
    if fetch_latest and region == DEFAULT_REGION:
        # download_infodengue._to_raw_readings_shape() hardcodes region=REGION
        # (Rio) regardless of which geocode was fetched -- calling this for
        # any other REGION_GEOCODES entry would mislabel that city's data as
        # Rio de Janeiro. Only the real Rio region gets a live fetch here.
        load_readings(fetch_latest_week(), engine)

    result = run_review(disease, region, metric, engine=engine)
    status = _tool_result(check_status(engine, disease, region, metric))
    opinion = reviewer.review(disease, region, metric, result, status)
    reviewer.save_review(engine, result["decision_log_id"], opinion)

    return RunResult(
        decision_log_id=result["decision_log_id"],
        disease=disease,
        region=region,
        metric=metric,
        period_index=result["period_index"],
        flagged=result["flagged"],
        confidence=result["confidence"],
        reasoning=result["reasoning"],
        tool_calls_made=result["tool_calls_made"],
        llm_provider=result["llm_provider"],
        status=StatusResponse(**status),
        reviewer=ReviewerOpinion(**opinion),
    )


# ------------------------------------------------------------------- routes --

@app.post(
    "/runs",
    response_model=RunResult,
    tags=["runs"],
    summary="Run a single-region agent review",
    description=(
        "Runs the primary agent's review followed by an independent reviewer "
        "opinion, and writes one decision_log row. Synchronous -- can take a "
        "while if the LLM call falls through to a slower provider."
    ),
)
def create_run(body: RunRequest = RunRequest()) -> RunResult:
    return _run_one(body.disease, body.region, body.metric, body.fetch_latest)


@app.post(
    "/runs/sweep",
    response_model=list[RunResult],
    tags=["runs"],
    summary="Run reviews for every disease/region/metric with a stored baseline",
    description=(
        "Sweeps every (disease, region, metric) combination currently in the "
        "baselines table, not a hardcoded region list -- so it covers "
        "whatever's actually been baselined so far, disease-agnostically."
    ),
)
def sweep_runs() -> list[RunResult]:
    # ponytail: synchronous and sequential -- fine for the handful of
    # baselined combinations today. A job queue is the right fix if this
    # grows enough to risk Render's free-tier request timeout.
    with engine.connect() as conn:
        combos = conn.execute(text("SELECT DISTINCT disease, region, metric FROM baselines")).all()
    return [_run_one(disease, region, metric, fetch_latest=True) for disease, region, metric in combos]


@app.get(
    "/runs",
    response_model=RunsPage,
    tags=["runs"],
    summary="List past runs",
    description="Paginated decision_log history, optionally filtered by disease/region/metric/flagged.",
)
def list_runs(
    disease: Optional[str] = Query(default=None, description="Filter to a disease.", examples=["dengue"]),
    region: Optional[str] = Query(default=None, description="Filter to a region.", examples=["BRAZIL-RIO_DE_JANEIRO"]),
    metric: Optional[str] = Query(default=None, description="Filter to a metric.", examples=["estimated_cases"]),
    flagged: Optional[bool] = Query(default=None, description="Filter to flagged (true) or not-flagged (false) runs."),
    limit: int = Query(default=20, ge=1, le=100, description="Max rows to return."),
    offset: int = Query(default=0, ge=0, description="Rows to skip, for pagination."),
) -> RunsPage:
    filters, params = [], {"limit": limit, "offset": offset}
    for name, value in (("disease", disease), ("region", region), ("metric", metric), ("flagged", flagged)):
        if value is not None:
            filters.append(f"{name} = :{name}")
            params[name] = value
    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM decision_log {where}"), params).scalar_one()
        rows = conn.execute(
            text(f"SELECT * FROM decision_log {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            params,
        ).mappings().all()

    return RunsPage(total=total, limit=limit, offset=offset, runs=[DecisionLogEntry(**dict(r)) for r in rows])


@app.get(
    "/runs/{run_id}",
    response_model=DecisionLogEntry,
    tags=["runs"],
    summary="Get a single run by id",
)
def get_run(run_id: int = Path(description="decision_log row id.")) -> DecisionLogEntry:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM decision_log WHERE id = :id"), {"id": run_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no run with id {run_id}")
    return DecisionLogEntry(**dict(row))


@app.get(
    "/status/{disease}/{region}/{metric}",
    response_model=StatusResponse,
    tags=["data"],
    summary="Latest reading vs. baseline",
)
def get_status(
    disease: str = Path(examples=["dengue"]),
    region: str = Path(examples=["BRAZIL-RIO_DE_JANEIRO"]),
    metric: str = Path(examples=["estimated_cases"]),
) -> StatusResponse:
    return StatusResponse(**_tool_result(check_status(engine, disease, region, metric)))


@app.get(
    "/history/{disease}/{region}/{metric}",
    response_model=HistoryResponse,
    tags=["data"],
    summary="Recent weekly readings",
)
def get_history(
    disease: str = Path(examples=["dengue"]),
    region: str = Path(examples=["BRAZIL-RIO_DE_JANEIRO"]),
    metric: str = Path(examples=["estimated_cases"]),
    limit: int = Query(default=12, ge=1, le=520, description="How many recent weeks."),
) -> HistoryResponse:
    return HistoryResponse(**_tool_result(tool_get_history(engine, disease, region, metric, limit=limit)))


@app.get(
    "/forecast/{disease}/{region}/{metric}",
    response_model=ForecastResponse,
    tags=["data"],
    summary="Trained-model expected value for the current period",
)
def get_forecast(
    disease: str = Path(examples=["dengue"]),
    region: str = Path(examples=["BRAZIL-RIO_DE_JANEIRO"]),
    metric: str = Path(examples=["estimated_cases"]),
) -> ForecastResponse:
    return ForecastResponse(**_tool_result(check_forecast(engine, disease, region, metric)))


@app.get(
    "/regions",
    response_model=list[RegionInfo],
    tags=["data"],
    summary="Every disease/region/metric combination with data",
)
def list_regions() -> list[RegionInfo]:
    with engine.connect() as conn:
        readings = conn.execute(text("SELECT DISTINCT disease, region, metric FROM raw_readings")).all()
        baselined = {
            (d, r, m) for d, r, m in conn.execute(text("SELECT DISTINCT disease, region, metric FROM baselines")).all()
        }
    return [
        RegionInfo(disease=d, region=r, metric=m, has_baseline=(d, r, m) in baselined, live_climate_data=r in REGION_GEOCODES)
        for d, r, m in readings
    ]


@app.get("/health", response_model=HealthResponse, tags=["ops"], summary="Health check")
def health() -> HealthResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:  # noqa: BLE001 -- health check reports any DB failure, doesn't need to discriminate
        db_status = f"error: {exc}"
    return HealthResponse(status="ok", database=db_status)


@app.get(
    "/debug/sentry",
    tags=["ops"],
    summary="Trigger a test error, to verify Sentry is capturing",
    description="Raises a deliberate exception. Disabled (403) when ENV=production.",
)
def debug_sentry() -> None:
    if os.environ.get("ENV") == "production":
        raise HTTPException(status_code=403, detail="disabled in production")
    raise RuntimeError("src/api.py /debug/sentry: deliberate test error for Sentry verification")
