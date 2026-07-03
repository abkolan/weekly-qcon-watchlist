# weekly-qcon-watchlist

A curated QCon/InfoQ video backlog for learning from strong engineering talks
without drowning in conference archives.

QCon and InfoQ have years of valuable talks on distributed systems,
infrastructure, data platforms, reliability, architecture, engineering
leadership, and newer AI/ML infrastructure work. The problem is not scarcity.
The problem is deciding what is worth watching next, remembering what has
already been queued, and keeping the backlog fresh without manually revisiting
old conference pages.

This repo automates that curation loop.

```text
QCon/InfoQ source pages -> SQLite -> scoring/filtering -> GitHub Issues -> GitHub Project
```

The objective is not complete archival coverage. The objective is a practical
watch backlog: talks with enough signal to watch, skim, or read via transcript.

## What It Optimizes For

The scoring is intentionally biased toward engineering talks with durable value:

- production case studies
- distributed systems and reliability
- platform engineering, SRE, DevOps, observability
- databases, storage, streaming, and data infrastructure
- data engineering, pipelines, lakehouse/warehouse topics
- AI infrastructure, MLOps, LLMOps, model serving, evals, and data governance
- architecture and engineering leadership talks with concrete operating lessons

It intentionally de-emphasizes:

- generic beginner introductions
- vendor-heavy product demos
- vague transformation/process talks
- hype-heavy titles without operational substance

The filters are editable in `watchlist.toml`, so the taste of the backlog can
change without touching Python code.

## Current State

This is a working local-first automation system:

- Python CLI
- SQLite migrations
- deterministic scoring
- QCon/InfoQ crawling and parsing
- GitHub Issue sync
- GitHub Project sync
- CI workflow
- manual historical backfill workflow
- weekly scheduled workflow

SQLite is the source of truth. GitHub Issues and the GitHub Project are the
reading and tracking surfaces generated from that state.

The first real sync created:

- [#1 ETL Is Dead, Long Live Streams](https://github.com/abkolan/weekly-qcon-watchlist/issues/1)

## Dashboard

The GitHub Project is the watch board:

```text
QCon Watch Backlog
```

Status columns:

- `Backlog`: synced from the CLI, not yet selected
- `Queued`: actively planned for near-term watching
- `Watching`: currently in progress
- `Watched`: completed
- `Skipped`: intentionally not watching
- `Rewatch`: worth revisiting later

Project fields populated by the CLI:

- `Year`
- `Decision`
- `Score`
- `Speaker`
- `Conference`
- `Presentation URL`

New synced issues land in `Backlog`.

## Public vs Private Project

Making the Project public is useful if you want the dashboard to be a visible
learning roadmap. It lets other people see the queue, the topics being
prioritized, and which talks made the cut.

Keeping it private is better while the system is still being backfilled and tuned.
During that phase, the board is more operational than editorial: scores may
shift, low-quality talks may be discovered and skipped, and the status columns
may reflect personal watching habits rather than public recommendations.

Recommended path:

1. Keep the Project private while backfilling 2016-2025.
2. Keep the repository public if you want the automation and scoring approach to
   be visible.
3. Make the Project public later, once the backlog feels curated and the status
   taxonomy is stable.

Public issues already provide a shareable surface. The Project board can become
public when it feels like a useful dashboard rather than an active work queue.

## Data Strategy

The canonical database is:

```text
data/infoq.db
```

It is committed to the repository so GitHub Actions has durable sync state across
runs. This is what prevents duplicate GitHub issues.

The database stores compact canonical state:

- InfoQ presentation URL
- title, speaker, company, conference, year, track
- video/slides/transcript availability
- score, decision, reason, tags
- GitHub issue number, issue URL, issue node ID
- GitHub Project item ID
- watch status

It should not store large artifacts:

- cached HTML
- transcripts
- media files
- large response bodies

Generated caches, Markdown reports, CSV exports, and scratch DBs are ignored by
Git. Only `data/infoq.db` is tracked.

## Database Maintenance

The workflows run:

```bash
uv run infoq-watchlist db-maintenance \
  --vacuum-threshold-mb 5 \
  --fail-threshold-mb 25
```

Behavior:

- reports SQLite size as JSON
- runs `VACUUM` once the DB is at least 5 MB
- fails above 25 MB to catch accidental bloat before committing it

The current database is far smaller than 5 MB. The threshold exists to catch
growth early.

## Quick Start

Install dependencies:

```bash
uv sync --extra dev
```

Run tests:

```bash
uv run --extra dev pytest -q
```

Apply migrations:

```bash
uv run infoq-watchlist migrate
```

Preview the next 2016 GitHub issues without writing anything:

```bash
uv run infoq-watchlist github-sync --year 2016 --limit 5 --dry-run
```

Create a small batch of issues and add them to the Project:

```bash
uv run infoq-watchlist github-sync \
  --year 2016 \
  --limit 5 \
  --create-issues \
  --add-to-project
```

## Configuration

Editable scoring and source configuration lives in:

```text
watchlist.toml
```

Useful sections:

- `[sources]`: QCon seed URLs
- `[thresholds]`: decision cutoffs for `watch`, `skim`, `transcript`
- `[[signals]]`: weighted text signals and tags
- `[companies]`: preferred companies
- `[github]`: repo, Project, eligible decisions, batch limits

The current eligible GitHub decisions are:

```toml
eligible_decisions = ["watch", "skim", "transcript"]
```

Rows scored as `background` or `skip` stay in SQLite but are not synced to GitHub
unless the config changes later.

## CLI Commands

Migrate the database:

```bash
uv run infoq-watchlist migrate
```

Crawl configured QCon sources:

```bash
uv run infoq-watchlist crawl --start-year 2016 --end-year 2016 --enrich-details
```

Rescore existing rows after editing `watchlist.toml`:

```bash
uv run infoq-watchlist score
```

Render a historical Markdown report:

```bash
uv run infoq-watchlist report \
  --start-year 2016 \
  --end-year 2016 \
  --top-per-year 15
```

Render a weekly Markdown report:

```bash
uv run infoq-watchlist weekly --days 14 --top 10
```

Preview GitHub sync:

```bash
uv run infoq-watchlist github-sync --year 2016 --limit 25 --dry-run
```

Create issues and add them to the Project:

```bash
uv run infoq-watchlist github-sync \
  --year 2016 \
  --limit 25 \
  --create-issues \
  --add-to-project
```

Export current rows:

```bash
uv run infoq-watchlist export-csv
```

Check and compact SQLite if needed:

```bash
uv run infoq-watchlist db-maintenance
```

## GitHub Setup

This project uses `gh` for GitHub operations.

Local auth needs the `project` scope:

```bash
gh auth refresh -s project
gh auth status
```

GitHub Actions uses a repository secret:

```text
QCON_WATCHLIST_TOKEN
```

For the current workflow, use a GitHub classic personal access token with:

- `repo`
- `workflow`
- `project`

The built-in `GITHUB_TOKEN` can handle some repo operations, but Project updates
need the token with Project access.

## Workflows

### CI

`.github/workflows/ci.yml`

Runs on push to `main` and on pull requests. It only installs dependencies and
runs tests. It does not crawl InfoQ, create issues, update the Project, or commit
SQLite changes.

### Historical Seed

`.github/workflows/historical-seed.yml`

Manual workflow for controlled backfills.

Inputs:

- `start_year`
- `end_year`
- `limit`
- `dry_run`

Recommended use:

1. Run one year with `dry_run=true`.
2. Run the same year with `dry_run=false` and `limit=10` or `25`.
3. Repeat until dry-run returns no eligible rows.
4. Move to the next year.

Do not backfill 2016-2025 in one large run.

### Weekly Watchlist

`.github/workflows/weekly-watchlist.yml`

Scheduled weekly and manually dispatchable. This is the testing ground for 2026
and newer talks.

Manual runs default to dry-run. Scheduled runs create eligible issues and update
`data/infoq.db`.

## Backfill Strategy

Use historical backfill conservatively:

```text
2016: dry-run -> small write batch -> repeat
2017: dry-run -> small write batch -> repeat
...
2025: dry-run -> small write batch -> repeat
2026: weekly workflow test lane
```

The default batch size is 25. This is intentionally below GitHub's practical
content-generation limits and gives the SQLite sync state a chance to commit
between runs.

## Rate Limit Strategy

The sync command is designed to be idempotent:

- rows with `github_issue_number` are skipped
- created issue IDs are persisted immediately
- rate-limit failures stop the run cleanly
- already-created issues remain recorded
- `--dry-run` performs no GitHub writes

For large historical batches, prefer several small workflow runs over one large
run.

## Development Notes

Core package:

```text
infoq_watchlist/
```

Important modules:

- `cli.py`: command-line entrypoint
- `crawler.py`: fetching and cache behavior
- `parser.py`: InfoQ/QCon parsing
- `scoring.py`: deterministic ranking
- `storage.py`: SQLite reads/writes
- `migrations.py`: migration runner
- `github_sync.py`: GitHub issue and Project sync
- `report.py`: Markdown rendering

Tests:

```text
tests/
```

Run them before pushing:

```bash
uv run --extra dev pytest -q
```
