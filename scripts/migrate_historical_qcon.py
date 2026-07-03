from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import timezone, datetime
from pathlib import Path
from typing import Iterable

from infoq_watchlist.config import load_config
from infoq_watchlist.crawler import discover_listing_urls, fetch_url
from infoq_watchlist.migrations import migrate_db
from infoq_watchlist.parser import merge_detail, parse_detail, parse_listing, parse_schedule_links
from infoq_watchlist.scoring import score_talk
from infoq_watchlist.storage import upsert_talk


DEFAULT_DB = Path("data/infoq.db")


@dataclass(frozen=True, slots=True)
class HistoricalSource:
    """One QCon archive URL that can seed SQLite rows."""

    year: int
    source_name: str
    url: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Serializable result for one attempted historical source."""

    source: HistoricalSource
    status: str
    row_count: int
    error: str | None = None


def main(argv: list[str] | None = None) -> int:
    """Run a bounded historical crawl migration."""
    args = _build_parser().parse_args(argv)
    sources = list_pending_sources(
        args.db,
        start_year=args.start_year,
        end_year=args.end_year,
        limit=args.max_sources,
        retry_failed=args.retry_failed,
    )

    if args.dry_run:
        # Dry-run prints the exact source URLs the next write run will attempt.
        print(json.dumps({"mode": "dry-run", "count": len(sources), "sources": [asdict(source) for source in sources]}, indent=2))
        return 0

    results: list[MigrationResult] = []
    for source in sources:
        result = migrate_source(
            args.db,
            source,
            config_path=args.config,
            max_pages=args.max_pages,
            enrich_details=args.enrich_details,
        )
        record_source_state(args.db, result)
        results.append(result)

    print(json.dumps({"mode": "write", "count": len(results), "results": [_result_dict(result) for result in results]}, indent=2))
    return 0


def list_pending_sources(
    db_path: str | Path,
    start_year: int,
    end_year: int,
    limit: int,
    retry_failed: bool = False,
) -> list[HistoricalSource]:
    """Return latest-first QCon archive sources that still need migration."""
    attempted = _attempted_source_urls(db_path, retry_failed=retry_failed)
    pending = [source for source in iter_historical_sources(start_year, end_year) if source.url not in attempted]
    return pending[:limit]


def iter_historical_sources(start_year: int, end_year: int) -> Iterable[HistoricalSource]:
    """Generate known QCon archive URL patterns newest year first."""
    for year in range(end_year, start_year - 1, -1):
        # QCon SF is late-year, then New York, then London, so this is roughly
        # reverse calendar order within each year.
        yield HistoricalSource(year, "qcon-sf", f"https://www.infoq.com/conferences/qconsf{year}/")
        yield HistoricalSource(year, "qcon-newyork", f"https://www.infoq.com/qcon-newyork-{year}/")
        yield HistoricalSource(year, "qcon-london", f"https://www.infoq.com/qcon-london-{year}/")


def migrate_source(
    db_path: str | Path,
    source: HistoricalSource,
    config_path: str,
    max_pages: int,
    enrich_details: bool,
) -> MigrationResult:
    """Crawl one source URL, score rows, and upsert them into SQLite."""
    config = load_config(config_path)
    try:
        row_count = 0
        for html, base_url in _fetch_pages(source.url, max_pages=max_pages):
            talks = parse_listing(html, base_url=base_url)
            if not talks:
                talks = parse_schedule_links(html, base_url=base_url)
            for talk in talks:
                if enrich_details:
                    # Detail fetches improve titles/speakers but should not
                    # discard a row when one detail page is temporarily flaky.
                    talk = _enrich_or_keep(talk)
                upsert_talk(db_path, score_talk(talk, config))
                row_count += 1
        return MigrationResult(source=source, status="success", row_count=row_count)
    except Exception as exc:
        # Record failed sources so the scheduled migration can continue to the
        # next archive URL; reruns can opt into --retry-failed.
        return MigrationResult(source=source, status="failed", row_count=0, error=str(exc)[:500])


def record_source_state(db_path: str | Path, result: MigrationResult) -> None:
    """Persist an attempted source URL so future runs can resume."""
    migrate_db(db_path)
    attempted_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO historical_crawl_state (
              source_url, year, source_name, status, row_count, error, attempted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_url) DO UPDATE SET
              status = excluded.status,
              row_count = excluded.row_count,
              error = excluded.error,
              attempted_at = excluded.attempted_at
            """,
            (
                result.source.url,
                result.source.year,
                result.source.source_name,
                result.status,
                result.row_count,
                result.error,
                attempted_at,
            ),
        )


def _fetch_pages(seed_url: str, max_pages: int) -> list[tuple[str, str]]:
    """Fetch a seed page and bounded pagination pages."""
    pages: list[tuple[str, str]] = []
    fetched_urls: set[str] = set()
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


def _enrich_or_keep(talk):
    """Return detail-enriched metadata, falling back to the listing row."""
    detail_url = talk.presentation_url or talk.url
    try:
        return merge_detail(talk, parse_detail(fetch_url(detail_url), detail_url))
    except Exception:
        return talk


def _attempted_source_urls(db_path: str | Path, retry_failed: bool) -> set[str]:
    """Read source URLs that should be skipped on this run."""
    # Failed sources are normally skipped so automation keeps moving; manual
    # repair runs can retry them while still skipping successful sources.
    where = "WHERE status = 'success'" if retry_failed else ""
    if not Path(db_path).exists():
        return set()
    with sqlite3.connect(db_path) as conn:
        try:
            rows = conn.execute(f"SELECT source_url FROM historical_crawl_state {where}").fetchall()
        except sqlite3.OperationalError:
            return set()
    return {row[0] for row in rows}


def _result_dict(result: MigrationResult) -> dict[str, object]:
    """Flatten nested dataclasses for JSON output."""
    return {
        "source": asdict(result.source),
        "status": result.status,
        "row_count": result.row_count,
        "error": result.error,
    }


def _build_parser() -> argparse.ArgumentParser:
    """Define script arguments without adding another CLI dependency."""
    parser = argparse.ArgumentParser(prog="migrate_historical_qcon")
    parser.add_argument("--config", default="watchlist.toml")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--max-sources", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--enrich-details", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
