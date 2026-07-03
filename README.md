# weekly-qcon-watchlist

Local-first automation for building a high-signal QCon/InfoQ video watch backlog.

The system crawls configured QCon/InfoQ source pages, stores talk metadata in
SQLite, scores talks with editable deterministic filters, and syncs eligible
videos into GitHub Issues and a GitHub Project board.

```text
QCon source pages -> SQLite -> scoring/filtering -> GitHub Issues -> GitHub Project
```

The goal is not complete QCon archival coverage. The goal is a useful backlog of
presentations worth watching: distributed systems, infrastructure, data
platforms, data pipelines, MLOps/AI infrastructure, observability, reliability,
and production engineering case studies.

## Current State

This repo has a working Python CLI, SQLite migrations, GitHub issue/project sync,
GitHub Actions workflows, and tests.

The first real sync has already created one issue and Project item:

- [#1 ETL Is Dead, Long Live Streams](https://github.com/abkolan/weekly-qcon-watchlist/issues/1)

SQLite is the source of truth. GitHub Issues and the Project board are generated
views over the SQLite state.

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

## Data Model

The canonical database is:

```text
data/infoq.db
```

It is intentionally committed to the repository so GitHub Actions has durable
sync state across workflow runs. This prevents duplicate issue creation.

The database stores:

- InfoQ presentation URL
- title, speaker, company, conference, year, track
- video/slides/transcript availability
- score, decision, reason, tags
- GitHub issue number, issue URL, issue node ID
- GitHub Project item ID
- watch status

The database should not store:

- cached HTML
- transcripts
- media files
- large response bodies

Generated HTML caches, Markdown reports, CSV exports, and scratch DBs are ignored
by Git. Only `data/infoq.db` is tracked.

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

Current size is much smaller than that. The 5 MB threshold is there as an early
maintenance trigger, not because the current dataset needs it.

## Configuration

Editable scoring and source configuration lives in:

```text
watchlist.toml
```

Change this file when you want to tune what gets promoted into the backlog.
GitHub Actions reads it on each run.

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

Rows scored as `background` or `skip` stay in SQLite but are not synced to
GitHub unless the config changes later.

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

## GitHub Project

The Project is:

```text
QCon Watch Backlog
```

Current Status options:

- `Backlog`
- `Queued`
- `Watching`
- `Watched`
- `Skipped`
- `Rewatch`

CLI-managed fields:

- `Year`
- `Decision`
- `Score`
- `Speaker`
- `Conference`
- `Presentation URL`

New synced issues land in `Backlog`.

## Public vs Private Project

Making the Project public is reasonable if the board is meant to be a visible
learning backlog. It lets others see what you plan to watch and which topics you
are prioritizing.

Keep it private if you want freedom to:

- reorder aggressively without explaining the priority model
- keep watch status personal
- add notes later that may be rough, subjective, or incomplete
- avoid making abandoned/skipped items look like public recommendations

The safe default is:

1. Keep the Project private while backfilling 2016-2025.
2. Make the repository public if you want the code/workflows visible.
3. Make the Project public later once the board has enough signal and the status
   taxonomy feels stable.

Public issues are already a useful sharing surface. The Project board can stay
private until it becomes a curated product rather than an operational queue.

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

## Project Spec

Detailed backlog and design notes live in:

```text
SPEC.md
```
