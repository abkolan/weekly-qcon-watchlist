import json
import sqlite3

from infoq_watchlist import cli, storage
from infoq_watchlist.github_sync import (
    CreatedIssue,
    GitHubSyncSettings,
    ProjectItem,
    add_issue_to_project,
    build_issue_payload,
    create_issue,
)
from infoq_watchlist.models import Talk
from infoq_watchlist.storage import upsert_talk


def _settings() -> GitHubSyncSettings:
    return GitHubSyncSettings(
        repo="abkolan/weekly-qcon-watchlist",
        project_owner="abkolan",
        project_title="QCon Watch Backlog",
        project_number=1,
        eligible_decisions=("watch", "skim", "transcript"),
        batch_limit=25,
        sleep_seconds=0,
        default_status="Backlog",
    )


def test_build_issue_payload_is_deterministic():
    talk = Talk(
        url="https://www.infoq.com/presentations/etl-streams/",
        presentation_url="https://www.infoq.com/presentations/etl-streams/",
        title="ETL Is Dead, Long Live Streams",
        year=2016,
        speaker="Neha Narkhede",
        conference="QCon SF",
        score=17,
        decision="watch",
        reason="Kafka and data infrastructure",
        tags=["data", "infra"],
    )

    payload = build_issue_payload(talk)

    assert payload.title == "[2016][QCon SF] ETL Is Dead, Long Live Streams"
    assert payload.labels == (
        "decision/watch",
        "qcon",
        "topic/data",
        "topic/infra",
        "video",
        "year/2016",
    )
    assert "- Presentation: https://www.infoq.com/presentations/etl-streams/" in payload.body
    assert "- Score: 17" in payload.body


def test_create_issue_uses_gh_and_returns_identifiers():
    calls = []

    def runner(args, input_text=None):
        calls.append(args)
        if args[:3] == ["gh", "issue", "create"]:
            return "https://github.com/abkolan/weekly-qcon-watchlist/issues/123\n"
        if args[:3] == ["gh", "issue", "view"]:
            return json.dumps(
                {
                    "number": 123,
                    "url": "https://github.com/abkolan/weekly-qcon-watchlist/issues/123",
                    "id": "I_123",
                }
            )
        return ""

    issue = create_issue(
        _settings(),
        build_issue_payload(Talk(url="https://www.infoq.com/presentations/a/", title="A", decision="watch")),
        runner=runner,
    )

    assert issue == CreatedIssue(
        number=123,
        url="https://github.com/abkolan/weekly-qcon-watchlist/issues/123",
        node_id="I_123",
    )
    assert any(call[:3] == ["gh", "label", "create"] for call in calls)
    assert any(call[:3] == ["gh", "issue", "create"] for call in calls)


def test_add_issue_to_project_sets_known_fields():
    calls = []

    def runner(args, input_text=None):
        calls.append(args)
        if args[:3] == ["gh", "project", "view"]:
            return json.dumps({"id": "PVT_project"})
        if args[:3] == ["gh", "project", "field-list"]:
            return json.dumps(
                {
                    "fields": [
                        {
                            "id": "status_field",
                            "name": "Status",
                            "type": "ProjectV2SingleSelectField",
                            "options": [{"id": "backlog_option", "name": "Backlog"}],
                        },
                        {"id": "year_field", "name": "Year", "type": "ProjectV2Field"},
                        {"id": "score_field", "name": "Score", "type": "ProjectV2Field"},
                        {"id": "url_field", "name": "Presentation URL", "type": "ProjectV2Field"},
                    ]
                }
            )
        if args[:3] == ["gh", "project", "item-add"]:
            return json.dumps({"id": "PVTI_1"})
        return "{}"

    item = add_issue_to_project(
        _settings(),
        CreatedIssue(123, "https://github.com/abkolan/weekly-qcon-watchlist/issues/123", "I_123"),
        Talk(
            url="https://www.infoq.com/presentations/etl-streams/",
            title="ETL",
            presentation_url="https://www.infoq.com/presentations/etl-streams/",
            year=2016,
            score=17,
            decision="watch",
        ),
        runner=runner,
    )

    assert item == ProjectItem(item_id="PVTI_1")
    assert any("--single-select-option-id" in call and "backlog_option" in call for call in calls)
    assert any("--field-id" in call and "year_field" in call and "--number" in call for call in calls)
    assert any("--field-id" in call and "url_field" in call and "--text" in call for call in calls)


def test_add_issue_to_project_matches_fields_with_ui_whitespace():
    calls = []

    def runner(args, input_text=None):
        calls.append(args)
        if args[:3] == ["gh", "project", "view"]:
            return json.dumps({"id": "PVT_project"})
        if args[:3] == ["gh", "project", "field-list"]:
            return json.dumps(
                {
                    "fields": [
                        {
                            "id": "status_field",
                            "name": "Status",
                            "type": "ProjectV2SingleSelectField",
                            "options": [{"id": "backlog_option", "name": "Backlog"}],
                        },
                        {"id": "url_field", "name": "Presentation URL ", "type": "ProjectV2Field"},
                    ]
                }
            )
        if args[:3] == ["gh", "project", "item-add"]:
            return json.dumps({"id": "PVTI_1"})
        return "{}"

    add_issue_to_project(
        _settings(),
        CreatedIssue(123, "https://github.com/abkolan/weekly-qcon-watchlist/issues/123", "I_123"),
        Talk(
            url="https://www.infoq.com/presentations/etl-streams/",
            title="ETL",
            presentation_url="https://www.infoq.com/presentations/etl-streams/",
            decision="watch",
        ),
        runner=runner,
    )

    assert not any(call[:3] == ["gh", "project", "field-create"] and "Presentation URL" in call for call in calls)
    assert any("--field-id" in call and "url_field" in call and "--text" in call for call in calls)


def test_cli_github_sync_dry_run_does_not_create_issues(tmp_path, capsys):
    db_path = tmp_path / "infoq.db"
    upsert_talk(
        db_path,
        Talk(
            url="https://www.infoq.com/presentations/etl-streams/",
            title="ETL Is Dead",
            year=2016,
            score=17,
            decision="watch",
        ),
    )

    exit_code = cli.main(["--db", str(db_path), "github-sync", "--year", "2016", "--dry-run"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["count"] == 1
    assert output["issues"][0]["title"] == "[2016][QCon] ETL Is Dead"


def test_cli_github_sync_create_issues_records_state(tmp_path, monkeypatch):
    db_path = tmp_path / "infoq.db"
    url = "https://www.infoq.com/presentations/etl-streams/"
    upsert_talk(db_path, Talk(url=url, title="ETL Is Dead", year=2016, score=17, decision="watch"))

    monkeypatch.setattr(cli, "create_issue", lambda settings, payload: CreatedIssue(123, "https://github.com/x/y/issues/123", "I_123"))
    monkeypatch.setattr(cli, "sleep_between_writes", lambda seconds: None)

    exit_code = cli.main(["--db", str(db_path), "github-sync", "--year", "2016", "--create-issues"])

    assert exit_code == 0
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT github_issue_number, github_issue_url, github_issue_node_id FROM talks WHERE url = ?",
            (url,),
        ).fetchone()
    assert row == (123, "https://github.com/x/y/issues/123", "I_123")


def test_cli_github_sync_does_not_duplicate_synced_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "infoq.db"
    url = "https://www.infoq.com/presentations/etl-streams/"
    upsert_talk(db_path, Talk(url=url, title="ETL Is Dead", year=2016, score=17, decision="watch"))
    monkeypatch.setattr(cli, "create_issue", lambda settings, payload: CreatedIssue(123, "https://github.com/x/y/issues/123", "I_123"))
    monkeypatch.setattr(cli, "sleep_between_writes", lambda seconds: None)

    first = cli.main(["--db", str(db_path), "github-sync", "--year", "2016", "--create-issues"])
    second = cli.main(["--db", str(db_path), "github-sync", "--year", "2016", "--create-issues"])

    assert first == 0
    assert second == 0


def test_cli_github_sync_add_to_project_records_item(tmp_path, monkeypatch):
    db_path = tmp_path / "infoq.db"
    url = "https://www.infoq.com/presentations/etl-streams/"
    upsert_talk(db_path, Talk(url=url, title="ETL Is Dead", year=2016, score=17, decision="watch"))
    monkeypatch.setattr(cli, "create_issue", lambda settings, payload: CreatedIssue(123, "https://github.com/x/y/issues/123", "I_123"))
    monkeypatch.setattr(cli, "add_issue_to_project", lambda settings, issue, talk: ProjectItem("PVTI_123"))
    monkeypatch.setattr(cli, "sleep_between_writes", lambda seconds: None)

    exit_code = cli.main(["--db", str(db_path), "github-sync", "--year", "2016", "--create-issues", "--add-to-project"])

    assert exit_code == 0
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT github_project_item_id FROM talks WHERE url = ?", (url,)).fetchone()
    assert row[0] == "PVTI_123"


def test_cli_github_sync_rate_limit_stops_cleanly(tmp_path, monkeypatch):
    db_path = tmp_path / "infoq.db"
    upsert_talk(db_path, Talk(url="https://www.infoq.com/presentations/a/", title="A", year=2016, score=30, decision="watch"))
    upsert_talk(db_path, Talk(url="https://www.infoq.com/presentations/b/", title="B", year=2016, score=20, decision="watch"))

    calls = {"count": 0}

    def fake_create(settings, payload):
        calls["count"] += 1
        if calls["count"] == 1:
            return CreatedIssue(1, "https://github.com/x/y/issues/1", "I_1")
        raise RuntimeError("secondary rate limit")

    monkeypatch.setattr(cli, "create_issue", fake_create)
    monkeypatch.setattr(cli, "sleep_between_writes", lambda seconds: None)

    exit_code = cli.main(["--db", str(db_path), "github-sync", "--year", "2016", "--create-issues"])

    assert exit_code == 2
    with sqlite3.connect(db_path) as conn:
        synced = conn.execute("SELECT count(*) FROM talks WHERE github_issue_number IS NOT NULL").fetchone()[0]
    assert synced == 1


def test_cli_github_backfill_defaults_to_configured_2030_window(tmp_path, capsys):
    db_path = tmp_path / "infoq.db"
    upsert_talk(
        db_path,
        Talk(
            url="https://www.infoq.com/presentations/future-platform/",
            title="Future Platform Operations",
            year=2030,
            score=20,
            decision="watch",
        ),
    )

    exit_code = cli.main(["--db", str(db_path), "github-backfill", "--limit", "1", "--dry-run"])

    # The default window should include future-safe rows through 2030.
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["start_year"] == 2016
    assert output["end_year"] == 2030
    assert output["issues"][0]["title"] == "[2030][QCon] Future Platform Operations"


def test_cli_github_backfill_repairs_project_items_before_creating_issues(tmp_path, monkeypatch):
    db_path = tmp_path / "infoq.db"
    repair_url = "https://www.infoq.com/presentations/repair/"
    create_url = "https://www.infoq.com/presentations/create/"
    upsert_talk(db_path, Talk(url=repair_url, title="Repair Me", year=2025, decision="watch", score=20))
    upsert_talk(db_path, Talk(url=create_url, title="Create Me", year=2025, decision="watch", score=10))
    calls = []

    def fake_add_to_project(settings, issue, talk):
        calls.append(("project", issue.number, talk.title))
        return ProjectItem(f"PVTI_{issue.number}")

    def fake_create_issue(settings, payload):
        calls.append(("create", payload.title))
        return CreatedIssue(36, "https://github.com/x/y/issues/36", "I_36")

    storage.record_github_issue(db_path, repair_url, 35, "https://github.com/x/y/issues/35", "I_35")
    monkeypatch.setattr(cli, "add_issue_to_project", fake_add_to_project)
    monkeypatch.setattr(cli, "create_issue", fake_create_issue)
    monkeypatch.setattr(cli, "sleep_between_writes", lambda seconds: None)

    exit_code = cli.main(
        [
            "--db",
            str(db_path),
            "github-backfill",
            "--start-year",
            "2025",
            "--end-year",
            "2025",
            "--limit",
            "2",
            "--create-issues",
            "--add-to-project",
        ]
    )

    assert exit_code == 0
    assert calls == [
        ("project", 35, "Repair Me"),
        ("create", "[2025][QCon] Create Me"),
        ("project", 36, "Create Me"),
    ]
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT title, github_issue_number, github_project_item_id FROM talks ORDER BY title"
        ).fetchall()
    assert rows == [("Create Me", 36, "PVTI_36"), ("Repair Me", 35, "PVTI_35")]
