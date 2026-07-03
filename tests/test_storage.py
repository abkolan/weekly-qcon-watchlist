import sqlite3
from datetime import date, datetime

from infoq_watchlist import storage
from infoq_watchlist.models import Talk
from infoq_watchlist.storage import init_db, list_talks, upsert_talk


def test_upsert_talk_is_idempotent_by_url(tmp_path):
    db_path = tmp_path / "infoq.db"
    init_db(db_path)

    first_version = Talk(
        url="https://www.infoq.com/presentations/platform-reliability/",
        title="Platform Reliability",
        summary="Original summary",
        year=2024,
        speaker="Alex Chen",
        company="Temporal",
        topics=["platform engineering"],
        score=9.0,
        decision="skim",
        reason="initial score",
        tags=["platform"],
    )
    updated_version = Talk(
        url=first_version.url,
        title="Platform Reliability at Scale",
        summary="Updated summary",
        year=2024,
        speaker="Alex Chen",
        company="Temporal",
        topics=["platform engineering", "reliability"],
        score=17.0,
        decision="watch",
        reason="updated score",
        tags=["platform", "reliability"],
    )

    upsert_talk(db_path, first_version)
    upsert_talk(db_path, updated_version)
    talks = list_talks(db_path)

    # Reusing the same URL should update the row instead of inserting a duplicate.
    assert len(talks) == 1
    assert talks[0].url == first_version.url
    assert talks[0].presentation_url == first_version.url
    assert talks[0].title == "Platform Reliability at Scale"
    assert talks[0].score == 17.0
    assert talks[0].decision == "watch"
    assert talks[0].topics == ["platform engineering", "reliability"]
    assert talks[0].tags == ["platform", "reliability"]


def test_list_talks_filters_by_year_range(tmp_path):
    db_path = tmp_path / "infoq.db"
    init_db(db_path)

    # Insert talks on both sides of the requested window.
    upsert_talk(
        db_path,
        Talk(
            url="https://www.infoq.com/presentations/old/",
            title="Old Talk",
            year=2022,
            topics=[],
            tags=[],
        ),
    )
    upsert_talk(
        db_path,
        Talk(
            url="https://www.infoq.com/presentations/current/",
            title="Current Talk",
            year=2024,
            topics=[],
            tags=[],
        ),
    )

    talks = list_talks(db_path, start_year=2024, end_year=2024)

    # Report generation depends on storage returning only the requested years.
    assert [talk.title for talk in talks] == ["Current Talk"]


def test_mark_reported_updates_matching_talk_reporting_state(tmp_path):
    db_path = tmp_path / "infoq.db"
    init_db(db_path)
    reported_urls = [
        "https://www.infoq.com/presentations/platform-reliability/",
        "https://www.infoq.com/presentations/data-platform/",
    ]

    for url in [*reported_urls, "https://www.infoq.com/presentations/unmatched/"]:
        # Use the public model and upsert path so the test exercises real storage rows.
        upsert_talk(
            db_path,
            Talk(
                url=url,
                title=url.rsplit("/", 2)[-2].replace("-", " ").title(),
                score=10.0,
                decision="watch",
                topics=[],
                tags=[],
            ),
        )

    storage.mark_reported(
        db_path,
        reported_urls,
        issue_number=42,
        issue_url="https://github.com/example/repo/issues/42",
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = {
            row["url"]: row
            for row in conn.execute(
                """
                SELECT url, watch_status, last_reported_at, issue_number, issue_url
                FROM talks
                """
            ).fetchall()
        }

    for url in reported_urls:
        # A reported talk should carry enough state to skip future issue batches.
        assert rows[url]["watch_status"] == "queued"
        assert rows[url]["issue_number"] == 42
        assert rows[url]["issue_url"] == "https://github.com/example/repo/issues/42"
        assert datetime.fromisoformat(rows[url]["last_reported_at"])

    assert rows["https://www.infoq.com/presentations/unmatched/"]["issue_number"] is None
    assert rows["https://www.infoq.com/presentations/unmatched/"]["issue_url"] is None


def test_list_unreported_talks_filters_decisions_and_sorts_by_score(tmp_path):
    db_path = tmp_path / "infoq.db"
    init_db(db_path)
    talks = [
        Talk(
            url="https://www.infoq.com/presentations/high-watch/",
            title="High Watch",
            score=20.0,
            decision="watch",
            topics=[],
            tags=[],
        ),
        Talk(
            url="https://www.infoq.com/presentations/low-watch/",
            title="Low Watch",
            score=12.0,
            decision="watch",
            topics=[],
            tags=[],
        ),
        Talk(
            url="https://www.infoq.com/presentations/top-skim/",
            title="Top Skim",
            score=30.0,
            decision="skim",
            topics=[],
            tags=[],
        ),
        Talk(
            url="https://www.infoq.com/presentations/reported-watch/",
            title="Reported Watch",
            score=99.0,
            decision="watch",
            topics=[],
            tags=[],
        ),
    ]
    for talk in talks:
        upsert_talk(db_path, talk)

    with sqlite3.connect(db_path) as conn:
        # Pre-mark the highest scoring watch talk so only issue-ready rows remain.
        conn.execute(
            "UPDATE talks SET issue_number = 7 WHERE url = ?",
            ("https://www.infoq.com/presentations/reported-watch/",),
        )

    unreported = storage.list_unreported_talks(db_path, decisions=["watch", "skim"])

    # The issue batch should ignore already reported talks and prioritize score.
    assert [talk.title for talk in unreported] == ["Top Skim", "High Watch", "Low Watch"]


def test_upsert_talk_persists_direct_presentation_url(tmp_path):
    db_path = tmp_path / "infoq.db"

    upsert_talk(
        db_path,
        Talk(
            url="infoq:platform-engineering-lessons",
            presentation_url="https://www.infoq.com/presentations/platform-engineering-lessons/",
            title="Platform Engineering Lessons",
            topics=[],
            tags=[],
        ),
    )

    talks = list_talks(db_path)

    # The direct presentation URL is stored separately from any internal row key.
    assert talks[0].url == "infoq:platform-engineering-lessons"
    assert talks[0].presentation_url == "https://www.infoq.com/presentations/platform-engineering-lessons/"


def test_list_github_sync_candidates_filters_synced_and_limits(tmp_path):
    db_path = tmp_path / "infoq.db"
    talks = [
        Talk(url="https://www.infoq.com/presentations/a/", title="A", year=2016, score=30, decision="watch"),
        Talk(url="https://www.infoq.com/presentations/b/", title="B", year=2016, score=20, decision="skim"),
        Talk(url="https://www.infoq.com/presentations/c/", title="C", year=2016, score=10, decision="background"),
        Talk(url="https://www.infoq.com/presentations/d/", title="D", year=2017, score=40, decision="watch"),
    ]
    for talk in talks:
        upsert_talk(db_path, talk)
    storage.record_github_issue(
        db_path,
        "https://www.infoq.com/presentations/a/",
        issue_number=10,
        issue_url="https://github.com/abkolan/weekly-qcon-watchlist/issues/10",
        issue_node_id="I_10",
    )

    candidates = storage.list_github_sync_candidates(
        db_path,
        decisions=["watch", "skim", "transcript"],
        year=2016,
        limit=25,
    )

    # GitHub sync should exclude low-priority and already-created issue rows.
    assert [talk.title for talk in candidates] == ["B"]


def test_list_github_sync_candidates_can_walk_latest_first(tmp_path):
    db_path = tmp_path / "infoq.db"
    talks = [
        Talk(url="https://www.infoq.com/presentations/old/", title="Old", year=2024, published_date=date(2024, 12, 1), score=99, decision="watch"),
        Talk(url="https://www.infoq.com/presentations/new-low/", title="New Low", year=2025, published_date=date(2025, 12, 1), score=10, decision="watch"),
        Talk(url="https://www.infoq.com/presentations/new-high/", title="New High", year=2025, published_date=date(2025, 11, 1), score=90, decision="watch"),
    ]
    for talk in talks:
        upsert_talk(db_path, talk)

    candidates = storage.list_github_sync_candidates(
        db_path,
        decisions=["watch"],
        start_year=2024,
        end_year=2025,
        limit=3,
        latest_first=True,
    )

    # Scheduled backfill should start at the newest month, then move backward.
    assert [talk.title for talk in candidates] == ["New Low", "New High", "Old"]


def test_list_github_project_repair_candidates_returns_missing_project_items(tmp_path):
    db_path = tmp_path / "infoq.db"
    missing_url = "https://www.infoq.com/presentations/missing-project/"
    complete_url = "https://www.infoq.com/presentations/complete-project/"
    upsert_talk(db_path, Talk(url=missing_url, title="Missing Project", year=2025, decision="watch"))
    upsert_talk(db_path, Talk(url=complete_url, title="Complete Project", year=2025, decision="watch"))
    storage.record_github_issue(db_path, missing_url, 35, "https://github.com/x/y/issues/35", "I_35")
    storage.record_github_issue(db_path, complete_url, 36, "https://github.com/x/y/issues/36", "I_36")
    storage.record_github_project_item(db_path, complete_url, "PVTI_36")

    candidates = storage.list_github_project_repair_candidates(
        db_path,
        decisions=["watch"],
        start_year=2025,
        end_year=2025,
        limit=10,
        latest_first=True,
    )

    # Only rows with an issue but no Project item should be repaired.
    assert len(candidates) == 1
    assert candidates[0].talk.title == "Missing Project"
    assert candidates[0].issue_number == 35
    assert candidates[0].issue_node_id == "I_35"


def test_record_github_project_item_persists_item_id(tmp_path):
    db_path = tmp_path / "infoq.db"
    url = "https://www.infoq.com/presentations/project-item/"
    upsert_talk(db_path, Talk(url=url, title="Project Item", score=20, decision="watch"))

    storage.record_github_issue(
        db_path,
        url,
        issue_number=12,
        issue_url="https://github.com/abkolan/weekly-qcon-watchlist/issues/12",
        issue_node_id="I_12",
    )
    storage.record_github_project_item(db_path, url, "PVTI_123")

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT github_issue_number, github_issue_node_id, github_project_item_id, last_synced_at FROM talks WHERE url = ?",
            (url,),
        ).fetchone()

    assert row[0] == 12
    assert row[1] == "I_12"
    assert row[2] == "PVTI_123"
    assert datetime.fromisoformat(row[3])
