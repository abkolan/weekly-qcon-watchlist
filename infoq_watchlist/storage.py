from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from infoq_watchlist.migrations import migrate_db
from infoq_watchlist.models import Talk
from infoq_watchlist.parser import _canonical_presentation_url


@dataclass(frozen=True, slots=True)
class GitHubProjectRepairCandidate:
    """Existing issue metadata for rows that still need Project sync."""

    talk: Talk
    issue_number: int
    issue_url: str
    issue_node_id: str | None


def init_db(path: str | Path) -> None:
    """Create or upgrade the SQLite database through migrations."""
    migrate_db(path)


def upsert_talk(path: str | Path, talk: Talk) -> None:
    """Insert or replace one talk by URL so repeated crawls are idempotent."""
    init_db(path)
    prepared = talk.with_timestamps()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO talks (
              url, presentation_url, title, summary, published_date, year, conference_year,
              speaker, company,
              duration_minutes, source, conference, track, view_count, like_count,
              topics, has_video, has_slides, has_transcript, score, decision,
              reason, tags, fetched_at, updated_at
            )
            VALUES (
              :url, :presentation_url, :title, :summary, :published_date, :year, :conference_year,
              :speaker, :company,
              :duration_minutes, :source, :conference, :track, :view_count,
              :like_count, :topics, :has_video, :has_slides, :has_transcript,
              :score, :decision, :reason, :tags, :fetched_at, :updated_at
            )
            ON CONFLICT(url) DO UPDATE SET
              title = excluded.title,
              presentation_url = excluded.presentation_url,
              summary = excluded.summary,
              published_date = excluded.published_date,
              year = excluded.year,
              conference_year = coalesce(excluded.conference_year, talks.conference_year),
              speaker = excluded.speaker,
              company = excluded.company,
              duration_minutes = excluded.duration_minutes,
              source = excluded.source,
              conference = excluded.conference,
              track = excluded.track,
              view_count = excluded.view_count,
              like_count = excluded.like_count,
              topics = excluded.topics,
              has_video = excluded.has_video,
              has_slides = excluded.has_slides,
              has_transcript = excluded.has_transcript,
              score = excluded.score,
              decision = excluded.decision,
              reason = excluded.reason,
              tags = excluded.tags,
              updated_at = excluded.updated_at
            """,
            _to_row(prepared),
        )


def list_talks(
    path: str | Path,
    start_year: int | None = None,
    end_year: int | None = None,
    decisions: list[str] | None = None,
    conference_year: int | None = None,
) -> list[Talk]:
    """Load talks from SQLite with optional year and decision filters.

    ``start_year``/``end_year`` filter on publication year; ``conference_year``
    filters on the QCon edition a talk was crawled from (often 1-2 years before
    it was published).
    """
    init_db(path)
    clauses: list[str] = []
    params: list[Any] = []

    if start_year is not None:
        clauses.append("year >= ?")
        params.append(start_year)
    if end_year is not None:
        clauses.append("year <= ?")
        params.append(end_year)
    if conference_year is not None:
        clauses.append("conference_year = ?")
        params.append(conference_year)
    if decisions:
        clauses.append(f"decision IN ({','.join('?' for _ in decisions)})")
        params.extend(decisions)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM talks {where} ORDER BY year, decision, score DESC, title"

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    return [_from_row(row) for row in rows]


def list_unreported_talks(
    path: str | Path,
    decisions: list[str] | None = None,
    limit: int | None = None,
) -> list[Talk]:
    """Return talks that have not yet been included in a GitHub issue."""
    init_db(path)
    clauses = ["issue_number IS NULL"]
    params: list[Any] = []
    if decisions:
        clauses.append(f"decision IN ({','.join('?' for _ in decisions)})")
        params.extend(decisions)

    sql = f"SELECT * FROM talks WHERE {' AND '.join(clauses)} ORDER BY score DESC, year DESC, title"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    return [_from_row(row) for row in rows]


def list_github_sync_candidates(
    path: str | Path,
    decisions: list[str],
    year: int | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    recent_days: int | None = None,
    limit: int = 25,
    latest_first: bool = False,
) -> list[Talk]:
    """Return eligible talks that do not already have a GitHub issue."""
    init_db(path)
    clauses = [
        "t.github_issue_number IS NULL",
        "t.issue_number IS NULL",
        # Avoid duplicate GitHub issues when historical rows differ only by URL slash style.
        """
        NOT EXISTS (
          SELECT 1
          FROM talks synced
          WHERE rtrim(coalesce(synced.presentation_url, synced.url), '/') = rtrim(coalesce(t.presentation_url, t.url), '/')
            AND (synced.github_issue_number IS NOT NULL OR synced.issue_number IS NOT NULL)
        )
        """,
    ]
    params: list[Any] = []

    if decisions:
        clauses.append(f"t.decision IN ({','.join('?' for _ in decisions)})")
        params.extend(decisions)
    if year is not None:
        clauses.append("t.year = ?")
        params.append(year)
    if start_year is not None:
        clauses.append("t.year >= ?")
        params.append(start_year)
    if end_year is not None:
        clauses.append("t.year <= ?")
        params.append(end_year)
    if recent_days is not None:
        clauses.append("t.published_date >= date('now', ?)")
        params.append(f"-{recent_days} days")

    # Scheduled historical backfills should walk from newest dated talks toward
    # older material. Manual yearly sync keeps the older score-first ordering.
    order_by = "year DESC, published_date DESC, score DESC, title" if latest_first else "score DESC, year DESC, title"
    sql = f"""
        WITH candidates AS (
          SELECT
            t.*,
            row_number() OVER (
              PARTITION BY rtrim(coalesce(t.presentation_url, t.url), '/')
              ORDER BY t.score DESC, t.title
            ) AS canonical_rank
          FROM talks t
          WHERE {' AND '.join(clauses)}
        )
        SELECT * FROM candidates
        WHERE canonical_rank = 1
        ORDER BY {order_by}
        LIMIT ?
    """
    params.append(limit)

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    return [_from_row(row) for row in rows]


def list_github_project_repair_candidates(
    path: str | Path,
    decisions: list[str],
    start_year: int | None = None,
    end_year: int | None = None,
    limit: int = 25,
    latest_first: bool = False,
) -> list[GitHubProjectRepairCandidate]:
    """Return created issues that still need a GitHub Project item id."""
    init_db(path)
    clauses = [
        "github_issue_number IS NOT NULL",
        "github_issue_url IS NOT NULL",
        "github_project_item_id IS NULL",
    ]
    params: list[Any] = []

    if decisions:
        clauses.append(f"decision IN ({','.join('?' for _ in decisions)})")
        params.extend(decisions)
    if start_year is not None:
        clauses.append("year >= ?")
        params.append(start_year)
    if end_year is not None:
        clauses.append("year <= ?")
        params.append(end_year)

    # Repair rows in the same direction as the scheduled creator so interrupted
    # runs resume the most recent unfinished work first.
    order_by = "year DESC, published_date DESC, score DESC, title" if latest_first else "score DESC, year DESC, title"
    sql = f"""
        SELECT * FROM talks
        WHERE {' AND '.join(clauses)}
        ORDER BY {order_by}
        LIMIT ?
    """
    params.append(limit)

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    return [
        GitHubProjectRepairCandidate(
            talk=_from_row(row),
            issue_number=int(row["github_issue_number"]),
            issue_url=str(row["github_issue_url"]),
            issue_node_id=row["github_issue_node_id"],
        )
        for row in rows
    ]


def mark_reported(path: str | Path, urls: list[str], issue_number: int, issue_url: str) -> None:
    """Attach talks to a GitHub issue and mark new items as queued."""
    if not urls:
        return

    init_db(path)
    reported_at = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join("?" for _ in urls)
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"""
            UPDATE talks
            SET issue_number = ?,
                issue_url = ?,
                last_reported_at = ?,
                watch_status = CASE WHEN watch_status = 'new' THEN 'queued' ELSE watch_status END
            WHERE url IN ({placeholders})
            """,
            [issue_number, issue_url, reported_at, *urls],
        )


def record_github_issue(
    path: str | Path,
    talk_url: str,
    issue_number: int,
    issue_url: str,
    issue_node_id: str | None,
) -> None:
    """Persist a created GitHub issue so sync is idempotent."""
    init_db(path)
    synced_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            UPDATE talks
            SET github_issue_number = ?,
                github_issue_url = ?,
                github_issue_node_id = ?,
                issue_number = ?,
                issue_url = ?,
                last_synced_at = ?,
                watch_status = CASE WHEN watch_status = 'new' THEN 'queued' ELSE watch_status END
            WHERE url = ?
            """,
            (issue_number, issue_url, issue_node_id, issue_number, issue_url, synced_at, talk_url),
        )


def record_github_project_item(path: str | Path, talk_url: str, project_item_id: str) -> None:
    """Persist the GitHub Project item id after adding an issue to a project."""
    init_db(path)
    synced_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            UPDATE talks
            SET github_project_item_id = ?,
                last_synced_at = ?
            WHERE url = ?
            """,
            (project_item_id, synced_at, talk_url),
        )


def _to_row(talk: Talk) -> dict[str, Any]:
    """Convert Python types into SQLite-friendly values."""
    return {
        # Canonicalize at the storage boundary so trailing-slash variants of the
        # same InfoQ presentation collapse onto one ON CONFLICT(url) key, even for
        # crawl paths that bypass the parser's canonicalization.
        "url": _canonical_presentation_url(talk.url),
        "presentation_url": _canonical_presentation_url(talk.presentation_url or talk.url),
        "title": talk.title,
        "summary": talk.summary,
        "published_date": talk.published_date.isoformat() if talk.published_date else None,
        "year": talk.year,
        "conference_year": talk.conference_year,
        "speaker": talk.speaker,
        "company": talk.company,
        "duration_minutes": talk.duration_minutes,
        "source": talk.source,
        "conference": talk.conference,
        "track": talk.track,
        "view_count": talk.view_count,
        "like_count": talk.like_count,
        "topics": json.dumps(talk.topics),
        "has_video": int(talk.has_video),
        "has_slides": int(talk.has_slides),
        "has_transcript": int(talk.has_transcript),
        "score": talk.score,
        "decision": talk.decision,
        "reason": talk.reason,
        "tags": json.dumps(talk.tags),
        "fetched_at": talk.fetched_at.isoformat() if talk.fetched_at else None,
        "updated_at": talk.updated_at.isoformat() if talk.updated_at else None,
    }


def _from_row(row: sqlite3.Row) -> Talk:
    """Convert one SQLite row into a Talk dataclass."""
    return Talk(
        url=row["url"],
        presentation_url=row["presentation_url"] or row["url"],
        title=row["title"],
        summary=row["summary"],
        published_date=_parse_date(row["published_date"]),
        year=row["year"],
        conference_year=row["conference_year"],
        speaker=row["speaker"],
        company=row["company"],
        duration_minutes=row["duration_minutes"],
        source=row["source"],
        conference=row["conference"],
        track=row["track"],
        view_count=row["view_count"],
        like_count=row["like_count"],
        topics=json.loads(row["topics"] or "[]"),
        has_video=bool(row["has_video"]),
        has_slides=bool(row["has_slides"]),
        has_transcript=bool(row["has_transcript"]),
        score=row["score"],
        decision=row["decision"],
        reason=row["reason"],
        tags=json.loads(row["tags"] or "[]"),
        fetched_at=_parse_datetime(row["fetched_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _parse_date(value: str | None) -> date | None:
    """Parse ISO dates from SQLite."""
    return date.fromisoformat(value) if value else None


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetimes from SQLite."""
    return datetime.fromisoformat(value) if value else None
