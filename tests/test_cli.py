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
