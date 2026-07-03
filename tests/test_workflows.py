from pathlib import Path


def test_historical_seed_workflow_has_dry_run_and_commit_steps():
    workflow = Path(".github/workflows/historical-seed.yml").read_text(encoding="utf-8")

    # Historical seeding must support safe previews and durable DB sync state.
    assert "workflow_dispatch" in workflow
    assert "dry_run" in workflow
    assert "github-sync" in workflow
    assert "--dry-run" in workflow
    assert "--create-issues" in workflow
    assert "db-maintenance --vacuum-threshold-mb 5 --fail-threshold-mb 25" in workflow
    assert "git add data/infoq.db" in workflow


def test_weekly_workflow_schedules_sync_and_uploads_report():
    workflow = Path(".github/workflows/weekly-watchlist.yml").read_text(encoding="utf-8")

    # Weekly automation should run on a schedule and keep reports inspectable.
    assert "schedule:" in workflow
    assert "github-sync" in workflow
    assert "--recent-days" in workflow
    assert "db-maintenance --vacuum-threshold-mb 5 --fail-threshold-mb 25" in workflow
    assert "actions/upload-artifact" in workflow
    assert "git add data/infoq.db" in workflow
