# Contagion Compass

An autonomous public health surveillance agent that monitors disease
surveillance data, distinguishes meaningful anomalies from normal seasonal
noise, investigates flagged anomalies further, and generates human-readable
reports — with a full log of its own reasoning at every step.

This isn't a dashboard bolted onto a cron job. It's a genuine agent loop:
**perceive** (pull the latest data) → **reason** (decide if anything needs
attention) → **act** (investigate further, forecast, report, alert) →
**observe** (log the outcome) → repeat on a schedule.

**Live dashboard:** [contagion-compass-dashboard.vercel.app](https://contagion-compass-dashboard.vercel.app)

---

## What it monitors

Weekly dengue fever surveillance for Rio de Janeiro, Brazil, via
[InfoDengue](https://info.dengue.mat.br) (Fiocruz/UFMG's nowcasting API),
compared against a 5-year seasonal baseline built from
[OpenDengue](https://opendengue.org)'s historical dataset. The schema and
agent prompts are disease-agnostic by design — every table and tool call
takes `disease`/`region`/`metric` as parameters, so a second disease is a
data-loading exercise, not a rewrite.

## How it reasons

Rather than a hardcoded "z-score > threshold → alert" rule, an LLM agent
with tool access makes the judgment call and explains it:

1. **Check status** — current reading vs. its historical baseline (mean,
   stddev, z-score).
2. **Investigate, if warranted** — the agent decides whether to pull a
   longer history window, check a trained forecasting model's independent
   expected range, cross-reference climate/Rt data, or compare against
   other major cities, before concluding.
3. **Second opinion** — an independent reviewer agent audits the primary
   verdict against the same data and can agree, disagree, or abstain — a
   built-in check against a single model's blind spots.
4. **Explain and log** — every run writes a full decision-log entry
   (data reviewed, tool calls made, reasoning, final verdict) whether or
   not anything was flagged. This is the explainability layer.

Every LLM call uses a **primary + fallback provider** pattern: a local
model (Ollama) is tried first, and any failure — unreachable, out of
memory, rate-limited — falls through to a hosted model (Gemini)
automatically. Cloud-scheduled runs skip straight to the fallback, since a
scheduled task has no path to a local model.

## Forecasting

Alongside the historical baseline, a [Prophet](https://facebook.github.io/prophet/)
model trained on prior weeks gives the agent a second, independent signal:
a trend/seasonality-based expected range for the current period, evaluated
with an honest train/test split (not just eyeballed).

## Reporting

Every run produces two versions of the same findings from the same
underlying data — no extra model call, just different framing:

- **Policymaker report** — numbers-first: the verdict, baseline
  comparison, z-score, a recommended action, and the agent's full
  reasoning.
- **Plain-language report** — a headline verdict and a narrative
  explanation first, with the technical detail still available underneath,
  not hidden.

Both include a generated trend chart, and either can trigger a Slack alert
when something's flagged.

## Dashboard & natural-language queries

A public web dashboard lists every run — verdict, numbers, reasoning,
second opinion, trend chart, and links to both reports — reading from a
small JSON manifest per run rather than the production database, so the
public-facing site never touches the operational Postgres instance. A
query box lets you ask ad hoc questions about run history in plain
English ("how many runs have been flagged this month?").

## Deployment

Containerized with Docker and deployed on AWS: RDS for the database, S3
for reports/charts/manifests, and a scheduled ECS task (EventBridge cron,
EC2 launch type) running the agent weekly, matching the data source's own
update cadence — no infrastructure sitting idle waiting for a schedule
that mostly wouldn't fire.

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python (agent + pipeline), JavaScript (dashboard) |
| LLM orchestration | Native tool-calling — Ollama (primary) + Gemini (fallback) |
| Forecasting | Prophet |
| Data analysis | pandas, numpy |
| Database | PostgreSQL (RDS in production) |
| Containerization | Docker |
| Cloud | AWS (S3, RDS, ECS, EventBridge, IAM, SSM) |
| Dashboard | Next.js (App Router), deployed on Vercel |
| Notifications | Slack incoming webhook |

## Project structure

```
src/
  ingest/       # data source pulls (InfoDengue, OpenDengue)
  analysis/     # baselines, z-scores, Prophet forecasting
  agent/        # tool definitions, primary agent loop, reviewer agent
  db/           # schema + connection
  report.py     # Markdown report rendering (both audiences) + S3 upload
  notify.py     # Slack alerting
scripts/        # entry points (run_agent, refresh_baseline, evaluate_forecast, ...)
tests/          # self-contained checks, no live DB/LLM required
dashboard/      # Next.js app reading run manifests from S3
```

## Running locally

```bash
docker compose up -d postgres          # local Postgres
pip install -r requirements.txt
cp .env.example .env                   # fill in at least GEMINI_API_KEY

python -m scripts.refresh_baseline_infodengue   # one-time: build the baseline
python -m scripts.run_agent                     # run the agent once
```

Or run the whole thing containerized:

```bash
docker compose up -d postgres
docker compose build agent
docker compose run --rm agent
```

## Testing

Every module with real logic has a self-contained check (no live DB/LLM
required):

```bash
python -m tests.test_reasoner_loop
python -m tests.test_reviewer_loop
python -m tests.test_report
python -m tests.test_forecast
python -m tests.test_notify
python -m tests.test_infodengue_climate
```
