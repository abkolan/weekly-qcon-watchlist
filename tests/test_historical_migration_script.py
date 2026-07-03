import json
import sqlite3

from scripts import migrate_historical_qcon as historical

from infoq_watchlist.storage import list_talks


def test_iter_historical_sources_walks_newest_year_first():
    sources = list(historical.iter_historical_sources(2024, 2025))

    # Backfill discovery should start from the newest year and late-year event.
    assert [source.url for source in sources[:4]] == [
        "https://www.infoq.com/conferences/qconsf2025/",
        "https://www.infoq.com/qcon-newyork-2025/",
        "https://www.infoq.com/qcon-london-2025/",
        "https://www.infoq.com/conferences/qconsf2024/",
    ]


def test_pending_sources_skip_attempted_urls_and_can_retry_failures(tmp_path):
    db_path = tmp_path / "infoq.db"
    success = historical.MigrationResult(
        source=historical.HistoricalSource(2025, "qcon-sf", "https://www.infoq.com/conferences/qconsf2025/"),
        status="success",
        row_count=2,
    )
    failed = historical.MigrationResult(
        source=historical.HistoricalSource(2025, "qcon-newyork", "https://www.infoq.com/qcon-newyork-2025/"),
        status="failed",
        row_count=0,
        error="not found",
    )
    historical.record_source_state(db_path, success)
    historical.record_source_state(db_path, failed)

    default_pending = historical.list_pending_sources(db_path, start_year=2025, end_year=2025, limit=3)
    retry_pending = historical.list_pending_sources(
        db_path,
        start_year=2025,
        end_year=2025,
        limit=3,
        retry_failed=True,
    )

    # Normal automation skips all attempted sources; repair runs may retry failed sources.
    assert [source.source_name for source in default_pending] == ["qcon-london"]
    assert [source.source_name for source in retry_pending] == ["qcon-newyork", "qcon-london"]


def test_migrate_source_uses_schedule_links_and_records_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "infoq.db"
    html = """
    <html>
      <body>
        <a href="/presentations/distributed-runtime/">Distributed Runtime</a>
        <a href="/presentations/platform-scaling/">Platform Scaling</a>
      </body>
    </html>
    """

    monkeypatch.setattr(historical, "fetch_url", lambda url: html)
    source = historical.HistoricalSource(2025, "qcon-sf", "https://www.infoq.com/conferences/qconsf2025/")

    result = historical.migrate_source(
        db_path,
        source,
        config_path="watchlist.toml",
        max_pages=1,
        enrich_details=False,
    )
    historical.record_source_state(db_path, result)

    talks = list_talks(db_path, start_year=2025, end_year=2025)
    with sqlite3.connect(db_path) as conn:
        state = conn.execute(
            "SELECT status, row_count FROM historical_crawl_state WHERE source_url = ?",
            (source.url,),
        ).fetchone()

    # Schedule pages without dates still seed rows from their archive year.
    assert result.status == "success"
    assert result.row_count == 2
    assert [talk.title for talk in talks] == ["Distributed Runtime", "Platform Scaling"]
    assert state == ("success", 2)


def test_script_dry_run_prints_next_source(tmp_path, capsys):
    db_path = tmp_path / "infoq.db"

    exit_code = historical.main(
        [
            "--db",
            str(db_path),
            "--start-year",
            "2025",
            "--end-year",
            "2025",
            "--max-sources",
            "1",
            "--dry-run",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    # Dry-runs must be safe previews for manual workflow dispatches.
    assert exit_code == 0
    assert output["mode"] == "dry-run"
    assert output["sources"][0]["url"] == "https://www.infoq.com/conferences/qconsf2025/"
