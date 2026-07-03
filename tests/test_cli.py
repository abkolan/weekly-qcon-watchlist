import json

from infoq_watchlist.cli import main
from infoq_watchlist.storage import list_talks


def test_cli_crawl_score_report_from_fixture(tmp_path):
    db_path = tmp_path / "infoq.db"
    report_path = tmp_path / "watchlist.md"

    crawl_code = main([
        "--db",
        str(db_path),
        "crawl",
        "--fixture",
        "tests/fixtures/infoq_listing.html",
    ])
    report_code = main([
        "--db",
        str(db_path),
        "report",
        "--start-year",
        "2024",
        "--end-year",
        "2026",
        "--output",
        str(report_path),
    ])

    # The CLI should prove a local, no-network path end to end.
    talks = list_talks(db_path)
    assert crawl_code == 0
    assert report_code == 0
    assert len(talks) == 2
    assert report_path.exists()
    assert "Operating a Platform Control Plane at Scale" in report_path.read_text(encoding="utf-8")


def test_cli_db_maintenance_reports_size(tmp_path, capsys):
    db_path = tmp_path / "infoq.db"

    assert main(["--db", str(db_path), "migrate"]) == 0
    capsys.readouterr()
    assert main(["--db", str(db_path), "db-maintenance"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["path"] == str(db_path)
    assert output["vacuumed"] is False
    assert output["fail_threshold_mb"] == 25


def test_cli_db_maintenance_fails_above_threshold(tmp_path):
    db_path = tmp_path / "infoq.db"

    assert main(["--db", str(db_path), "migrate"]) == 0

    # A zero threshold is a deterministic way to exercise the guardrail.
    exit_code = main(["--db", str(db_path), "db-maintenance", "--fail-threshold-mb", "0"])

    assert exit_code == 2
