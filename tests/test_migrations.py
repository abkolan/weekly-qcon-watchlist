import sqlite3

from infoq_watchlist.cli import main
from infoq_watchlist.migrations import current_version, migrate_db


def test_migrate_db_records_applied_versions(tmp_path):
    db_path = tmp_path / "infoq.db"

    first_run = migrate_db(db_path)
    second_run = migrate_db(db_path)

    # Migration runs should be explicit, recorded, and safe to repeat.
    assert first_run == ["001", "002", "003", "004"]
    assert second_run == []
    assert current_version(db_path) == "004"

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        migration_rows = conn.execute("SELECT version, name FROM schema_migrations").fetchall()

    assert {"schema_migrations", "talks"}.issubset(tables)
    assert migration_rows == [
        ("001", "create_talks"),
        ("002", "add_reporting_state"),
        ("003", "add_presentation_url"),
        ("004", "add_github_sync_state"),
    ]


def test_cli_migrate_creates_database(tmp_path):
    db_path = tmp_path / "infoq.db"

    exit_code = main(["--db", str(db_path), "migrate"])

    # The CLI should be enough to stand up a fresh SQLite database.
    assert exit_code == 0
    assert db_path.exists()
    assert current_version(db_path) == "004"


def test_migrate_db_adds_reporting_state_columns(tmp_path):
    db_path = tmp_path / "infoq.db"

    applied = migrate_db(db_path)

    with sqlite3.connect(db_path) as conn:
        talk_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(talks)").fetchall()
        }

    # Reporting state lets issue publishing be idempotent across runs.
    assert applied == ["001", "002", "003", "004"]
    assert current_version(db_path) == "004"
    assert {
        "watch_status",
        "last_reported_at",
        "issue_number",
        "issue_url",
        "presentation_url",
        "github_issue_number",
        "github_issue_url",
        "github_issue_node_id",
        "github_project_item_id",
        "last_synced_at",
    }.issubset(talk_columns)
