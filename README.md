# weekly-qcon-watchlist

Python CLI for building a ranked InfoQ/QCon watchlist.

The tool will crawl InfoQ presentation pages, extract talk metadata, score talks
with deterministic and explainable signals, store results in SQLite, and generate
Markdown reports for historical backfills and weekly review.

## Current Status

This repository is at the specification stage. The active build plan and backlog
live in [SPEC.md](SPEC.md).

## Intended Workflow

Historical backfill:

```bash
infoq-watchlist migrate
infoq-watchlist crawl --start-year 2016 --end-year 2026 --max-pages 200 --enrich-details
infoq-watchlist score
infoq-watchlist report --start-year 2016 --end-year 2026 --top-per-year 15
```

Weekly watchlist:

```bash
infoq-watchlist weekly --days 14 --top 10
```

GitHub issue-ready batch:

```bash
infoq-watchlist issue-batch --title "InfoQ/QCon Historical Batch" --top 20
```

GitHub issue sync dry-run:

```bash
infoq-watchlist github-sync --year 2016 --limit 25 --dry-run
```

Create GitHub issues and add them to the manually-created Project:

```bash
infoq-watchlist github-sync --year 2016 --limit 25 --create-issues --add-to-project
```

Export:

```bash
infoq-watchlist export-csv
```

## Design Principles

- Keep the implementation local-first and CLI-first.
- Use SQLite as the source of truth for crawled and scored talks.
- Generate Markdown as the reading surface.
- Use GitHub Issues later as a weekly delivery surface, not as the database.
- Keep scoring terms in editable config so workflow behavior can change without code edits.
- Avoid LLM/API dependencies in v1.
- Avoid browser automation.

## Planned Outputs

- `data/infoq.db`: SQLite database of talks.
- `data/watchlist.md`: historical Markdown watchlist.
- Weekly Markdown report suitable for a GitHub issue.
- Issue-ready Markdown batch for GitHub issue creation.
- Optional CSV export.

Reports link through the stored `presentation_url` field, which should be the
direct public InfoQ presentation URL.

## Sources

Backfill source URLs are configured in `watchlist.toml` under
`[sources].qcon_seed_urls`. The 2016 seed set includes QCon London, QCon New
York, and QCon San Francisco.

## Database Migrations

SQLite schema changes are handled through numbered SQL files in
`infoq_watchlist/migrations/`.

```bash
infoq-watchlist migrate
```

Normal storage operations also call the same migration runner, so a fresh
database can be created by either `migrate` or the first command that reads or
writes SQLite.

## GitHub Automation

The CLI can create one GitHub issue per eligible video and optionally add the
issue to a GitHub Project.

Before using Project sync, refresh local GitHub CLI auth with the project scope:

```bash
gh auth refresh -s project
```

For GitHub Actions, create a secret named `QCON_WATCHLIST_TOKEN` with `repo` and
`project` access. If that secret is absent, issue creation may work with
`GITHUB_TOKEN`, but Project updates are expected to fail.

Workflows:

- `Historical QCon Seed`: manual workflow for year-range backfills.
- `Weekly QCon Watchlist`: scheduled weekly workflow plus manual dry-run support.

## Development

Planned stack:

- Python 3.12
- `requests`
- `beautifulsoup4`
- `feedparser`
- `pydantic`
- `rich`
- `typer` or `argparse`
- `pytest`

See [SPEC.md](SPEC.md) for the detailed data model, scoring rules, backlog, and
acceptance criteria.
