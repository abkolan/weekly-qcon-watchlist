# weekly-qcon-watchlist Spec

## Goal

Build a Python CLI tool that creates ranked weekly and historical InfoQ/QCon
watchlists.

Given a date range, the tool crawls InfoQ presentation pages, extracts metadata,
scores talks with deterministic heuristics, stores the results in SQLite, and
generates Markdown reports.

Keep the implementation simple. Do not build a web app. Do not add LLM ranking
in v1. Do not over-engineer.

## Primary Use Case

Discover high-signal InfoQ/QCon talks from 2016 through 2026 relevant to:

- distributed systems
- platform engineering
- DevOps/SRE
- observability
- Kubernetes
- service mesh
- databases/storage/streaming
- data platforms
- data engineering
- data pipelines
- architecture
- control planes
- developer productivity
- engineering leadership
- AI infrastructure / LLMOps / MLOps infrastructure, mostly from 2022 onward

## Modes

### Historical Backfill

Backfill should be configurable by year range.

Default:

```bash
infoq-watchlist crawl --start-year 2016 --end-year 2026 --max-pages 200 --enrich-details
```

Recommended date policy:

- Default start year: 2016
- Earliest supported start year: 2007
- Default end year: current year
- Weekly mode must not run the full historical backfill

### Weekly Watchlist

Weekly mode should only consider recently published talks.

```bash
infoq-watchlist weekly --days 14 --top 10
```

Future GitHub Actions integration should create a GitHub issue containing the
weekly Markdown report.

## Outputs

1. SQLite database of talks.
2. Markdown watchlist grouped by year.
3. Weekly Markdown report suitable for a GitHub issue.
4. Issue-ready Markdown batch for historical GitHub issue creation.
5. Optional CSV export.

## Tech Constraints

- Python 3.12
- Use `requests`, `beautifulsoup4`, `feedparser`, `pydantic`, `rich`, `typer` or `argparse`, and `pytest`.
- Use SQLite through stdlib `sqlite3` unless SQLAlchemy becomes clearly useful.
- No browser automation.
- Be polite with crawling: user-agent, timeout, retries, and small sleep between requests.
- Cache fetched HTML locally to avoid repeatedly hitting InfoQ.
- Make it runnable locally from CLI.

## Repository Layout

- `README.md`
- `SPEC.md`
- `pyproject.toml`
- `watchlist.toml`
- `infoq_watchlist/`
  - `__init__.py`
  - `cli.py`
  - `crawler.py`
  - `parser.py`
  - `scoring.py`
  - `storage.py`
  - `migrations.py`
  - `migrations/`
    - `001_create_talks.sql`
  - `report.py`
  - `models.py`
- `tests/`
  - `test_scoring.py`
  - `test_parser.py`
  - `test_storage.py`
  - `test_report.py`
  - `fixtures/`
- `data/`
  - `cache/`
  - `infoq.db`
  - `watchlist.md`

## Configuration

Text filters and scoring weights must be easy to edit without changing Python
code. Store them in a repo-tracked config file:

- `watchlist.toml`

GitHub Actions should read this file on every run. If the user updates the
filters, companies, weights, or decision thresholds in `watchlist.toml`, the next
workflow run should use the new scoring behavior automatically.

The Python code should provide defaults for missing config fields, but the
repo-local config is the intended tuning surface.

Backfill source URLs should also live in `watchlist.toml`. For 2016, the QCon
seed list must include QCon London, QCon New York, and QCon San Francisco.

Example shape:

```toml
[backfill]
default_start_year = 2016
earliest_start_year = 2007

[thresholds]
watch = 16
skim = 10
transcript = 6
background = 3

[[signals]]
name = "production_case_study"
weight = 5
terms = [
  "migration",
  "postmortem",
  "incident",
  "outage",
  "scale",
  "latency",
  "reliability",
  "load shedding",
  "consistency",
  "rollback",
  "multi-region",
  "control plane",
]

[[signals]]
name = "data_infrastructure"
weight = 4
terms = [
  "data platform",
  "data pipeline",
  "data engineering",
  "stream processing",
  "Flink",
  "Spark",
  "Iceberg",
]

[companies]
preferred = [
  "Netflix",
  "Google",
  "Microsoft",
  "Meta",
  "Uber",
  "Stripe",
  "Shopify",
  "Cloudflare",
  "LinkedIn",
  "Airbnb",
  "Datadog",
  "Temporal",
  "OpenAI",
  "Anthropic",
  "Coinbase",
]
```

## CLI Commands

```bash
infoq-watchlist migrate
infoq-watchlist crawl --start-year 2016 --end-year 2026 --max-pages 200 --enrich-details
infoq-watchlist score
infoq-watchlist report --start-year 2016 --end-year 2026 --top-per-year 15
infoq-watchlist weekly --days 14 --top 10
infoq-watchlist issue-batch --title "InfoQ/QCon Historical Batch" --top 20
infoq-watchlist github-sync --year 2016 --limit 25 --dry-run
infoq-watchlist github-sync --year 2016 --limit 25 --create-issues --add-to-project
infoq-watchlist export-csv
```

## SQLite Data Model

SQLite is the source of truth for dedupe, rescoring, and repeatable report
generation. Markdown reports and GitHub issues are outputs generated from it.

Schema changes must be handled through numbered SQL migrations in
`infoq_watchlist/migrations/`. A `schema_migrations` table records applied
versions. The CLI exposes `infoq-watchlist migrate`, and storage operations call
the same migration runner before reading or writing.

### `talks`

- `url`: str, unique
- `presentation_url`: str, direct InfoQ presentation URL
- `title`: str
- `summary`: str | None
- `published_date`: date | None
- `year`: int | None
- `speaker`: str | None
- `company`: str | None
- `duration_minutes`: int | None
- `source`: str | None
- `conference`: str | None
- `track`: str | None
- `view_count`: int | None
- `like_count`: int | None
- `topics`: list[str]
- `has_video`: bool
- `has_slides`: bool
- `has_transcript`: bool
- `score`: float
- `decision`: watch | skim | transcript | background | skip
- `reason`: str
- `tags`: list[str]
- `fetched_at`: datetime
  - `updated_at`: datetime
  - `watch_status`: new | queued | watched | skipped | archived
  - `last_reported_at`: datetime | None
  - `issue_number`: int | None
  - `issue_url`: str | None
  - `github_issue_number`: int | None
  - `github_issue_url`: str | None
  - `github_issue_node_id`: str | None
  - `github_project_item_id`: str | None
  - `last_synced_at`: datetime | None

Store `topics` and `tags` as JSON text in v1. Do not add normalized join tables
unless the simple representation becomes painful.

## Scoring

Implement deterministic scoring in `scoring.py`.

Textual keyword matching should be only one part of the ranking. Prefer a small
set of explainable signals that can be extracted from InfoQ/QCon pages without
browser automation or paid APIs.

All text terms, company lists, weights, and decision thresholds should be loaded
from `watchlist.toml`. Keep built-in defaults in code only as a fallback for
missing config values.

### Metadata Signals

- QCon source or known QCon event page: +6
- Relevant conference track/topic metadata: +4
- Has transcript: +3
- Has video: +2
- Has slides: +1
- Practical duration range, 25-70 minutes: +1
- Strong speaker/company fit: +3
- Visible popularity signal, if present and parseable: +1 to +4
  examples: view count, like count, saves, or other stable InfoQ engagement counters
- Recent publication for weekly mode: +2

Do not depend on popularity signals existing. Treat them as optional fields. If
InfoQ does not expose a stable view count or like count in fetched HTML, skip
that part of the score and keep the rest deterministic.

### Positive Text Signals

- QCon / QCon London / QCon SF / QCon Plus: +6
- Production case study terms: +5
  terms: migration, postmortem, incident, outage, scale, latency, reliability, load shedding, consistency, rollback, multi-region, control plane
- Strong infra/platform terms: +4
  terms: distributed systems, Kubernetes, service mesh, platform engineering, observability, SRE, DevOps, database, storage, streaming, Kafka, tracing, workflows, Temporal
- Data infrastructure terms: +4
  terms: data platform, data pipeline, data engineering, data lake, data warehouse, lakehouse, ETL, ELT, CDC, event-driven, Flink, Spark, Iceberg, Delta Lake, Kafka Streams, stream processing
- AI/ML infrastructure terms: +4
  terms: AI infrastructure, ML infrastructure, MLOps, LLMOps, model serving, inference, feature store, vector database, embeddings, RAG, evals, agents, GPU, accelerator, training pipeline, model monitoring, data governance
- Speaker/company fit: +3
  companies: Netflix, Google, Microsoft, Meta, Uber, Stripe, Shopify, Cloudflare, LinkedIn, Airbnb, Datadog, Temporal, OpenAI, Anthropic, Coinbase
- Numbers/measurement terms: +2
  terms: p99, throughput, requests per second, error budget, SLO, SLA, availability, cost, deployment frequency, build time
- Failure-mode terms: +3
  terms: failed, broke, bottleneck, retry storm, overload, regression, what we got wrong, lessons learned
- Leadership/director relevance: +2
  terms: engineering strategy, developer productivity, platform adoption, org design, operating model, socio-technical

### Negative Text Signals

- Vendor marketing/hype: -6
  terms: unlock, unleash, transform, revolutionize, future of, next generation, AI-native, 10x
- Beginner content: -5
  terms: introduction to, getting started, basics, 101
- Generic agile/process content: -3
  terms: scrum, standup, agile transformation, SAFe
- Product demo/sponsored flavor: -5
  terms: demo, sponsored, product walkthrough

### Decision Thresholds

- score >= 16: watch
- score >= 10: skim
- score >= 6: transcript
- score >= 3: background
- else: skip

### Historical Adjustment

- For 2016-2018, boost microservices, DevOps, containers, tracing, control planes, resilience.
- For 2019-2022, boost Kubernetes production, platform teams, service mesh, observability, developer productivity, SRE, data platforms, streaming, data pipelines.
- For 2023-2026, boost AI infrastructure, MLOps infrastructure, LLMOps, evals, agents, data governance, data/AI platforms, platform engineering maturity, cost control.

## Report Format

Historical report:

```markdown
# InfoQ/QCon Watchlist: 2016-2026

## Summary

- total crawled
- total watch
- total skim
- total skipped
- date generated

## 2016

### Watch

1. Title - Speaker, Company - score
   - URL
   - Why: reason
   - Tags: ...

### Skim

...
```

Weekly report:

```markdown
# InfoQ/QCon Weekly Watchlist: YYYY-MM-DD

## Watch

...
```

## GitHub Workflow Direction

Use GitHub Actions for weekly delivery after the local CLI works.

Preferred flow:

1. Run the weekly command on a schedule.
2. Generate Markdown.
3. Create GitHub issues for eligible videos.
4. Upload the generated report and database/export as workflow artifacts.

Do not make GitHub Issues the source of truth. Use them as the delivery and watch
backlog surface. SQLite owns dedupe and GitHub sync state.

Persistence options to evaluate:

- Commit `data/infoq.db` so workflow runs keep durable sync state.
- Upload Markdown reports as workflow artifacts.
- Keep `data/cache/` out of git.

GitHub sync defaults:

- Eligible decisions: `watch`, `skim`, `transcript`.
- Default issue batch limit: `25`.
- Dry-run is available through `github-sync --dry-run`.
- GitHub Project views are created manually once; CLI manages issues, labels,
  Project items, and Project field values.

## Backlog

### Now

- [ ] Create Python package structure.
- [ ] Add `pyproject.toml` with CLI entrypoint.
- [ ] Add `watchlist.toml` as the editable scoring and backfill config.
- [ ] Define `Talk` model.
- [ ] Add migration runner and initial SQLite schema migration.
- [ ] Implement deterministic scoring.
- [ ] Add scoring tests.
- [ ] Implement SQLite storage with idempotent upsert by URL.
- [ ] Add storage tests with a temporary database.

### Next

- [ ] Implement polite HTTP fetching with local cache.
- [ ] Identify stable InfoQ/QCon listing pages or feeds for crawl seeds.
- [ ] Parse saved HTML fixtures for title, summary, date, speaker, company, duration, topics, media flags, and optional engagement counters.
- [ ] Add parser fixture tests.
- [ ] Implement historical report generation grouped by year and decision.
- [ ] Add report tests.

### Later

- [ ] Add weekly mode.
- [ ] Add CSV export.
- [ ] Add GitHub Actions workflow.
- [ ] Generate issue-ready Markdown batches from unreported SQLite rows.
- [ ] Add GitHub issue creation for weekly watchlists.
- [ ] Add `github-sync` dry-run and create-issues modes.
- [ ] Add Project item sync using `gh project`.
- [ ] Decide whether to persist SQLite, JSON, CSV, or only workflow artifacts in GitHub Actions.
- [ ] Add tuning docs for scoring terms, weights, thresholds, and company lists.

## Testing

- Unit tests for scoring.
- Parser tests using saved HTML fixtures.
- Storage tests using temporary SQLite DB files.
- Report tests asserting grouping by year and decision.

## Acceptance Criteria

- `pytest` passes.
- CLI can crawl at least a small number of pages.
- Duplicate URLs are handled idempotently.
- Re-running crawl does not duplicate rows.
- Report generation works from SQLite without re-crawling.
- Scoring is deterministic and explainable.
- SQLite schema can be created or upgraded through `infoq-watchlist migrate`.
- Text filters, company lists, weights, and thresholds can be changed through `watchlist.toml`.
- No LLM/API dependency in v1.
