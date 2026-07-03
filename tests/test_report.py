from infoq_watchlist import report
from infoq_watchlist.models import Talk
from infoq_watchlist.report import render_watchlist


def test_render_watchlist_groups_talks_by_year_and_decision():
    talks = [
        Talk(
            url="https://www.infoq.com/presentations/platform-teams/",
            title="Platform Teams in Production",
            year=2024,
            speaker="Priya Shah",
            company="Netflix",
            score=18.0,
            decision="watch",
            reason="platform engineering case study",
            tags=["platform"],
            topics=[],
        ),
        Talk(
            url="https://www.infoq.com/presentations/observability-rollout/",
            title="Observability Rollout Lessons",
            year=2024,
            speaker="Sam Rivera",
            company="Datadog",
            score=11.0,
            decision="skim",
            reason="observability rollout",
            tags=["observability"],
            topics=[],
        ),
        Talk(
            url="https://www.infoq.com/presentations/data-platform/",
            title="Data Platform Reliability",
            year=2023,
            speaker="Mina Patel",
            company="LinkedIn",
            score=16.0,
            decision="watch",
            reason="data platform reliability",
            tags=["data"],
            topics=[],
        ),
    ]

    markdown = render_watchlist(talks, start_year=2023, end_year=2024, top_per_year=15)

    # The report should expose the requested year range and per-decision buckets.
    assert "# InfoQ/QCon Watchlist: 2023-2024" in markdown
    assert "## 2023" in markdown
    assert "## 2024" in markdown
    assert "### Watch" in markdown
    assert "### Skim" in markdown
    assert "Data Platform Reliability" in markdown
    assert "Platform Teams in Production" in markdown
    assert "Observability Rollout Lessons" in markdown
    assert "Why: data platform reliability" in markdown
    assert "Tags: data" in markdown


def test_render_watchlist_applies_top_per_year_limit():
    talks = [
        Talk(
            url="https://www.infoq.com/presentations/high-score/",
            title="High Score Talk",
            year=2024,
            score=20.0,
            decision="watch",
            reason="highest score",
            tags=["top"],
            topics=[],
        ),
        Talk(
            url="https://www.infoq.com/presentations/lower-score/",
            title="Lower Score Talk",
            year=2024,
            score=19.0,
            decision="watch",
            reason="lower score",
            tags=["lower"],
            topics=[],
        ),
    ]

    markdown = render_watchlist(talks, start_year=2024, end_year=2024, top_per_year=1)

    # Limiting per year keeps historical reports concise and deterministic.
    assert "High Score Talk" in markdown
    assert "Lower Score Talk" not in markdown


def test_render_issue_batch_outputs_github_ready_checklist():
    talks = [
        Talk(
            url="https://www.infoq.com/presentations/platform-teams/",
            title="Platform Teams in Production",
            year=2024,
            speaker="Priya Shah",
            company="Netflix",
            score=18.0,
            decision="watch",
            reason="platform engineering case study",
            tags=["platform"],
            topics=[],
        ),
        Talk(
            url="https://www.infoq.com/presentations/observability-rollout/",
            title="Observability Rollout Lessons",
            year=2024,
            speaker="Sam Rivera",
            company="Datadog",
            score=11.0,
            decision="skim",
            reason="observability rollout",
            tags=["observability"],
            topics=[],
        ),
    ]

    markdown = report.render_issue_batch(talks, title="Weekly InfoQ Picks")

    # GitHub issue bodies should be actionable without another formatting step.
    assert markdown.startswith("# Weekly InfoQ Picks\n")
    assert "- [ ] [Platform Teams in Production](https://www.infoq.com/presentations/platform-teams/)" in markdown
    assert "- [ ] [Observability Rollout Lessons](https://www.infoq.com/presentations/observability-rollout/)" in markdown
    assert "18 (watch)" in markdown
    assert "11 (skim)" in markdown
    assert "Why: platform engineering case study" in markdown
    assert "Tags: platform" in markdown


def test_reports_prefer_direct_presentation_url():
    talk = Talk(
        url="infoq:architecture-scale-change",
        presentation_url="https://www.infoq.com/presentations/architecture-scale-change/",
        title="Architecture in the Lead",
        year=2025,
        score=18.0,
        decision="watch",
        reason="architecture scale case study",
        topics=[],
        tags=[],
    )

    markdown = render_watchlist([talk], start_year=2025, end_year=2025)
    issue_markdown = report.render_issue_batch([talk], title="Direct URL Check")

    # Reports must link to the public InfoQ presentation, not an internal row key.
    assert "URL: https://www.infoq.com/presentations/architecture-scale-change/" in markdown
    assert "[Architecture in the Lead](https://www.infoq.com/presentations/architecture-scale-change/)" in issue_markdown
