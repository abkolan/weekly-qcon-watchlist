from pathlib import Path


def test_ci_workflow_runs_tests_without_github_writes():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    # CI should validate code changes without crawling or mutating GitHub state.
    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert "uv run pytest -q" in workflow
    assert "github-sync" not in workflow


def test_historical_seed_workflow_has_dry_run_and_commit_steps():
    workflow = Path(".github/workflows/historical-seed.yml").read_text(encoding="utf-8")

    # Historical seeding must support safe previews and durable DB sync state.
    assert "workflow_dispatch" in workflow
    assert "dry_run" in workflow
    assert 'default: "2030"' in workflow
    assert "github-backfill" in workflow
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


def test_scheduled_backfill_runs_every_90_minutes_and_checkpoints_db():
    workflow = Path(".github/workflows/scheduled-backfill.yml").read_text(encoding="utf-8")

    # The alternating cron entries produce a 90-minute schedule in UTC.
    assert 'cron: "0 0-21/3 * * *"' in workflow
    assert 'cron: "30 1-22/3 * * *"' in workflow
    assert 'default: "2030"' in workflow
    assert "END_YEAR=${{ inputs.end_year || '2030' }}" in workflow
    assert "concurrency:" in workflow
    assert "scripts/migrate_historical_qcon.py" in workflow
    assert "Preview next historical crawl source" in workflow
    assert "Migrate next historical crawl source" in workflow
    assert "github-backfill" in workflow
    assert '--end-year "$END_YEAR"' in workflow
    assert "--create-issues" in workflow
    assert "--add-to-project" in workflow
    assert "status=$?" in workflow
    assert 'steps.backfill.outputs.status == \'2\'' in workflow
    assert "GitHub rate limit reached after checkpointing database state" in workflow
    assert "run: exit 2" not in workflow
    assert "git add data/infoq.db" in workflow
    assert "git push" in workflow
