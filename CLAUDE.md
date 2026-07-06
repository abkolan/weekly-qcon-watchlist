# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Local-first automation that curates a QCon/InfoQ video watch backlog. It crawls conference listing pages, parses talks, scores them deterministically from `watchlist.toml`, stores them in SQLite, and generates two "views" over that state: Markdown reports and GitHub Issues + a GitHub Project board.

Deliberate non-goals (do not add): web app, browser automation (Selenium/Playwright), a database server, or LLM-based ranking. Keep it runnable locally, inspectable in tests, and safe to run in small GitHub Actions batches.

## Commands

Uses `uv` (Python 3.12). The CLI entry point is `infoq-watchlist` (defined in `pyproject.toml` → `infoq_watchlist.cli:main`).

```bash
uv sync --extra dev                    # install deps (incl. pytest)
uv run --extra dev pytest -q           # run all tests
uv run --extra dev pytest tests/test_scoring.py -q          # single file
uv run --extra dev pytest tests/test_scoring.py::test_name  # single test
uv run infoq-watchlist <subcommand>    # run the CLI
```

Global CLI flags precede the subcommand: `--config` (default `watchlist.toml`), `--db` (default `data/infoq.db`).

Key subcommands (see README.md for full flag lists and workflows): `migrate`, `crawl`, `score`, `report`, `weekly`, `issue-batch`, `github-sync`, `github-backfill`, `export-csv`, `db-maintenance`.

There is no linter/formatter configured. Match existing style: `from __future__ import annotations`, frozen slotted dataclasses, module-private helpers prefixed `_`, and a one-line docstring on nearly every function.

## Architecture

Data flows one direction; SQLite is the single source of truth:

```
sources (watchlist.toml) → crawler → parser → scoring → storage (SQLite) → report / github_sync
```

Module responsibilities (`infoq_watchlist/`):

- `models.py` — the `Talk` dataclass, the one shared data structure passed between every stage.
- `config.py` — loads `watchlist.toml` into an immutable `WatchlistConfig` with built-in defaults; unknown/missing keys fall back to defaults.
- `crawler.py` — polite HTTP fetching with **on-disk HTML caching** in `data/cache/` (keyed by URL sha256). `read_fixture` loads local HTML so crawl paths are testable without network.
- `parser.py` — BeautifulSoup parsing of InfoQ listing/detail/schedule pages into `Talk`s.
- `scoring.py` — pure deterministic scoring: metadata weights + text `[[signals]]` → numeric score → `decision` bucket (`watch`/`skim`/`transcript`/`background`/`skip`) via `thresholds`. No side effects.
- `storage.py` — all SQL. Upserts by `url` (idempotent), and the `list_*` query helpers the CLI depends on. Auto-runs migrations on write.
- `migrations.py` — runner that applies numbered `.sql` files from `infoq_watchlist/migrations/` (`NNN_name.sql`), tracked in a `schema_migrations` table.
- `github_sync.py` — builds issue payloads and drives the **`gh` CLI via `subprocess`** for Issue + Project writes. Rate-limit-aware.
- `report.py` — renders Markdown (historical watchlist, weekly, issue batch).
- `cli.py` — argparse subcommands; thin orchestration over the modules above.

`scripts/migrate_historical_qcon.py` is a second entry point for bounded historical backfills. It records per-source progress in the `historical_crawl_state` table so scheduled runs resume from the next archive URL instead of recrawling.

## Critical invariants

- **`data/infoq.db` is tracked in git on purpose.** It is the durable sync ledger — it records `github_issue_number` / project item ids so reruns (local or CI) do not recreate already-synced issues. Do not delete it or `.gitignore` it. Keep it small: never store HTML, transcripts, or media in it (those go to the git-ignored `data/cache/`).
- **GitHub sync is idempotent and must stay that way.** Rows with an existing `github_issue_number` are skipped; created ids are recorded immediately after creation; rate-limit errors stop the run cleanly (exit code 2) rather than continuing. Interrupted runs may leave an issue created but not added to the Project — `github-backfill` repairs these before creating new state.
- **Scoring is config-driven, not code-driven.** To change what gets promoted/demoted, edit `[[signals]]` / `[thresholds]` / `[metadata_weights]` in `watchlist.toml`, then `uv run infoq-watchlist score` to rescore existing rows without recrawling. A signal adds its weight once per talk even if multiple terms match.
- **Schema changes go through a new numbered migration file**, never by editing an applied one. Migrations must be idempotent-safe; `migrations.py` records pre-existing schema (e.g. an already-present `talks` table for `001`) to avoid double-applying.
- **`--dry-run` must never perform GitHub writes.** Preview flows (`github-sync`/`github-backfill --dry-run`) print JSON only.

## GitHub Actions

Four workflows in `.github/workflows/`: `ci.yml` (tests on push/PR), `historical-seed.yml` (manual backfill), `scheduled-backfill.yml` (every 90 min, one small batch, walks newest→oldest year), `weekly-watchlist.yml` (weekly). Scheduled runs commit `data/infoq.db` when sync state changes. Project writes require the `QCON_WATCHLIST_TOKEN` secret (classic PAT with `repo`, `workflow`, `project`); the built-in `GITHUB_TOKEN` cannot update Projects.
