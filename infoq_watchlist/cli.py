from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from infoq_watchlist.config import load_config
from infoq_watchlist.crawler import discover_listing_urls, fetch_url, read_fixture
from infoq_watchlist.github_sync import (
    add_issue_to_project,
    build_issue_payload,
    create_issue,
    settings_from_config,
    sleep_between_writes,
)
from infoq_watchlist.migrations import current_version, migrate_db
from infoq_watchlist.parser import merge_detail, parse_detail, parse_listing, parse_schedule_links
from infoq_watchlist.report import render_issue_batch, render_weekly, render_watchlist
from infoq_watchlist.scoring import score_talk
from infoq_watchlist.storage import (
    list_github_sync_candidates,
    list_talks,
    list_unreported_talks,
    record_github_issue,
    record_github_project_item,
    upsert_talk,
)


DEFAULT_DB = Path("data/infoq.db")


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _build_parser() -> argparse.ArgumentParser:
    """Create subcommands without requiring a CLI framework dependency."""
    parser = argparse.ArgumentParser(prog="infoq-watchlist")
    parser.add_argument("--config", default="watchlist.toml")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    subparsers = parser.add_subparsers(required=True)

    migrate = subparsers.add_parser("migrate")
    migrate.set_defaults(func=_cmd_migrate)

    crawl = subparsers.add_parser("crawl")
    crawl.add_argument("--start-year", type=int)
    crawl.add_argument("--end-year", type=int)
    crawl.add_argument("--max-pages", type=int, default=1)
    crawl.add_argument("--url", action="append", default=[])
    crawl.add_argument("--fixture", action="append", default=[])
    crawl.add_argument("--enrich-details", action="store_true")
    crawl.set_defaults(func=_cmd_crawl)

    score = subparsers.add_parser("score")
    score.set_defaults(func=_cmd_score)

    report = subparsers.add_parser("report")
    report.add_argument("--start-year", type=int)
    report.add_argument("--end-year", type=int)
    report.add_argument("--top-per-year", type=int, default=15)
    report.add_argument("--output", default="data/watchlist.md")
    report.set_defaults(func=_cmd_report)

    weekly = subparsers.add_parser("weekly")
    weekly.add_argument("--days", type=int, default=14)
    weekly.add_argument("--top", type=int, default=10)
    weekly.add_argument("--output", default="data/weekly.md")
    weekly.set_defaults(func=_cmd_weekly)

    issue_batch = subparsers.add_parser("issue-batch")
    issue_batch.add_argument("--title", default="InfoQ/QCon Watchlist Batch")
    issue_batch.add_argument("--top", type=int, default=20)
    issue_batch.add_argument("--output", default="data/issue-batch.md")
    issue_batch.set_defaults(func=_cmd_issue_batch)

    github_sync = subparsers.add_parser("github-sync")
    github_sync.add_argument("--year", type=int)
    github_sync.add_argument("--recent-days", type=int)
    github_sync.add_argument("--limit", type=int)
    github_sync.add_argument("--sleep-seconds", type=float)
    github_sync.add_argument("--dry-run", action="store_true")
    github_sync.add_argument("--create-issues", action="store_true")
    github_sync.add_argument("--add-to-project", action="store_true")
    github_sync.set_defaults(func=_cmd_github_sync)

    export = subparsers.add_parser("export-csv")
    export.add_argument("--output", default="data/talks.csv")
    export.set_defaults(func=_cmd_export_csv)
    return parser


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Apply pending database migrations explicitly."""
    applied = migrate_db(args.db)
    version = current_version(args.db) or "none"
    if applied:
        print(f"applied migrations: {', '.join(applied)}")
    else:
        print(f"database already at version {version}")
    return 0


def _cmd_crawl(args: argparse.Namespace) -> int:
    """Fetch or read listing HTML, parse talks, score them, and upsert rows."""
    config = load_config(args.config)
    urls = args.url or list(config.qcon_seed_urls) or ["https://www.infoq.com/qcon/"]
    html_pages = [(read_fixture(path), "https://www.infoq.com/") for path in args.fixture]

    if not args.fixture:
        html_pages.extend(_fetch_listing_pages(urls, args.max_pages))

    count = 0
    for html, base_url in html_pages:
        talks = parse_listing(html, base_url=base_url)
        if not talks:
            talks = parse_schedule_links(html, base_url=base_url)
        for talk in talks:
            if _inside_year_range(talk.year, args.start_year, args.end_year):
                if args.enrich_details and not args.fixture:
                    talk = merge_detail(talk, parse_detail(fetch_url(talk.presentation_url or talk.url), talk.presentation_url or talk.url))
                if not _inside_year_range(talk.year, args.start_year, args.end_year):
                    continue
                upsert_talk(args.db, score_talk(talk, config))
                count += 1

    print(f"crawled {count} talks into {args.db}")
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    """Rescore all stored talks from the current editable config."""
    config = load_config(args.config)
    talks = list_talks(args.db)
    for talk in talks:
        upsert_talk(args.db, score_talk(talk, config))
    print(f"scored {len(talks)} talks")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Render a historical Markdown report from SQLite only."""
    config = load_config(args.config)
    start_year = args.start_year or config.default_start_year
    end_year = args.end_year or _max_year(args.db) or start_year
    talks = list_talks(args.db, start_year=start_year, end_year=end_year)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_watchlist(talks, start_year, end_year, args.top_per_year), encoding="utf-8")
    print(f"wrote {output}")
    return 0


def _cmd_weekly(args: argparse.Namespace) -> int:
    """Render a compact weekly report from already crawled/scored talks."""
    talks = [talk for talk in list_talks(args.db) if talk.decision in {"watch", "skim", "transcript"}]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_weekly(talks, top=args.top), encoding="utf-8")
    print(f"wrote {output}")
    return 0


def _cmd_issue_batch(args: argparse.Namespace) -> int:
    """Render unreported talks as a GitHub issue-ready Markdown batch."""
    talks = list_unreported_talks(args.db, decisions=["watch", "skim", "transcript"], limit=args.top)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_issue_batch(talks, args.title), encoding="utf-8")
    print(f"wrote {output}")
    return 0


def _cmd_github_sync(args: argparse.Namespace) -> int:
    """Create GitHub issues and optionally add them to a Project."""
    config = load_config(args.config)
    settings = settings_from_config(config.github)
    limit = args.limit or settings.batch_limit
    sleep_seconds = settings.sleep_seconds if args.sleep_seconds is None else args.sleep_seconds
    talks = list_github_sync_candidates(
        args.db,
        decisions=list(settings.eligible_decisions),
        year=args.year,
        recent_days=args.recent_days,
        limit=limit,
    )

    payloads = [{"url": talk.url, **asdict(build_issue_payload(talk))} for talk in talks]
    if args.dry_run or not args.create_issues:
        print(json.dumps({"mode": "dry-run", "count": len(payloads), "issues": payloads}, indent=2))
        return 0

    synced = 0
    for talk in talks:
        payload = build_issue_payload(talk)
        try:
            issue = create_issue(settings, payload)
            record_github_issue(args.db, talk.url, issue.number, issue.url, issue.node_id)
            synced += 1
            if args.add_to_project:
                project_item = add_issue_to_project(settings, issue, talk)
                record_github_project_item(args.db, talk.url, project_item.item_id)
            sleep_between_writes(sleep_seconds)
        except RuntimeError as exc:
            print(f"github-sync stopped after {synced} issue(s): {exc}")
            if "rate limit" in str(exc).casefold() or "secondary rate" in str(exc).casefold():
                return 2
            return 1

    print(f"github-sync created {synced} issue(s)")
    return 0


def _cmd_export_csv(args: argparse.Namespace) -> int:
    """Export current SQLite rows as a flat CSV for easy inspection."""
    talks = list_talks(args.db)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(talks[0]).keys()) if talks else ["url", "title"])
        writer.writeheader()
        for talk in talks:
            writer.writerow(asdict(talk))
    print(f"wrote {output}")
    return 0


def _inside_year_range(year: int | None, start_year: int | None, end_year: int | None) -> bool:
    """Keep undated talks and filter dated talks by requested year range."""
    if year is None:
        return True
    if start_year is not None and year < start_year:
        return False
    if end_year is not None and year > end_year:
        return False
    return True


def _fetch_listing_pages(seed_urls: list[str], max_pages: int) -> list[str]:
    """Fetch seed pages and statically discovered pagination URLs."""
    pages: list[tuple[str, str]] = []
    fetched_urls: set[str] = set()
    for seed_url in seed_urls:
        seed_html = fetch_url(seed_url)
        pages.append((seed_html, seed_url))
        fetched_urls.add(seed_url.rstrip("/"))
        for page_url in discover_listing_urls(seed_url, seed_html, max_pages):
            key = page_url.rstrip("/")
            if key in fetched_urls:
                continue
            pages.append((fetch_url(page_url), page_url))
            fetched_urls.add(key)
    return pages


def _max_year(db_path: str) -> int | None:
    """Find the latest stored year without exposing SQL in the CLI command."""
    years = [talk.year for talk in list_talks(db_path) if talk.year is not None]
    return max(years) if years else None


if __name__ == "__main__":
    raise SystemExit(main())
