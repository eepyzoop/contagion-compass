-- Disease-agnostic schema: every table is parameterized by disease/region/metric
-- so adding a new disease later is a data-loading task, not a schema change.

CREATE TABLE IF NOT EXISTS raw_readings (
    id              BIGSERIAL PRIMARY KEY,
    disease         TEXT NOT NULL,              -- e.g. 'dengue'
    region          TEXT NOT NULL,              -- e.g. 'BRAZIL' (country for now; state/province later)
    country_iso3    TEXT NOT NULL,              -- e.g. 'BRA'
    metric          TEXT NOT NULL,              -- e.g. 'reported_cases'
    period_start    DATE NOT NULL,              -- start of the reporting window
    period_end      DATE NOT NULL,              -- end of the reporting window
    resolution      TEXT NOT NULL,              -- 'week' | 'month' | 'year'
    value           DOUBLE PRECISION NOT NULL,
    source          TEXT NOT NULL,              -- e.g. 'OpenDengue-V1.3'
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (disease, region, metric, period_start, resolution, source)
);

CREATE INDEX IF NOT EXISTS idx_raw_readings_lookup
    ON raw_readings (disease, region, metric, period_start);

CREATE TABLE IF NOT EXISTS baselines (
    id                  BIGSERIAL PRIMARY KEY,
    disease             TEXT NOT NULL,
    region              TEXT NOT NULL,
    metric              TEXT NOT NULL,
    resolution          TEXT NOT NULL,          -- must match raw_readings.resolution
    period_index        INTEGER NOT NULL,       -- e.g. ISO week-of-year (1-53)
    historical_mean     DOUBLE PRECISION NOT NULL,
    historical_stddev   DOUBLE PRECISION NOT NULL,
    n_observations      INTEGER NOT NULL,       -- how many historical years fed this baseline
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (disease, region, metric, resolution, period_index)
);

CREATE TABLE IF NOT EXISTS decision_log (
    id              BIGSERIAL PRIMARY KEY,
    disease         TEXT NOT NULL,
    region          TEXT NOT NULL,
    metric          TEXT NOT NULL,
    period_index    INTEGER NOT NULL,
    flagged         BOOLEAN NOT NULL,
    confidence      TEXT NOT NULL,          -- 'low' | 'medium' | 'high'
    reasoning       TEXT NOT NULL,
    tool_calls_made INTEGER NOT NULL,
    llm_provider    TEXT NOT NULL,          -- 'ollama' | 'gemini'
    reviewer_agree    BOOLEAN,              -- NULL until the reviewer step runs (or if it fails)
    reviewer_notes    TEXT,
    reviewer_provider TEXT,                 -- 'ollama' | 'gemini' -- independent pick from llm_provider
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- decision_log already existed before the reviewer columns were added --
-- CREATE TABLE IF NOT EXISTS above is a no-op against an existing table,
-- so the new columns need an explicit migration for already-provisioned
-- databases (local Docker, RDS, Neon). Harmless no-op against a fresh
-- table too.
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS reviewer_agree BOOLEAN;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS reviewer_notes TEXT;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS reviewer_provider TEXT;

-- Phase 7 task 7: S3 object keys for this run's report/chart artifacts,
-- written back by src.report.upload_manifest() after upload. Lets the
-- dashboard get report/chart S3 keys from the /runs API (decision_log)
-- instead of only from the S3 manifest JSON -- see the 2026-08-21
-- dashboard-data-source decision.
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS report_key TEXT;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS report_key_public TEXT;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS chart_key TEXT;

-- Phase 7 task 7: the actual reading/baseline numbers behind each verdict --
-- previously only captured in the S3 manifest (src.report.upload_manifest),
-- not the DB itself, which meant decision_log alone couldn't fully explain
-- a run. Written by reasoner.review() via a check_status() call alongside
-- the existing period_index lookup.
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS period_start DATE;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS value DOUBLE PRECISION;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS baseline_mean DOUBLE PRECISION;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS baseline_stddev DOUBLE PRECISION;
ALTER TABLE decision_log ADD COLUMN IF NOT EXISTS z_score DOUBLE PRECISION;
