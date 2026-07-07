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
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
