from __future__ import annotations

from collections import defaultdict
from datetime import date

from infoq_watchlist.models import Talk


DECISION_ORDER = ["watch", "skim", "transcript", "background", "skip"]


def render_watchlist(
    talks: list[Talk],
    start_year: int,
    end_year: int,
    top_per_year: int = 15,
    title: str | None = None,
) -> str:
    """Render a historical Markdown watchlist grouped by year and decision."""
    report_title = title or f"InfoQ/QCon Watchlist: {start_year}-{end_year}"
    lines = [f"# {report_title}", "", "## Summary", ""]
    lines.extend(_summary_lines(talks))

    by_year: dict[int, list[Talk]] = defaultdict(list)
    for talk in talks:
        if talk.year is not None:
            by_year[talk.year].append(talk)

    for year in range(start_year, end_year + 1):
        year_talks = by_year.get(year, [])
        if not year_talks:
            continue
        lines.extend(["", f"## {year}"])
        for decision in DECISION_ORDER:
            decision_talks = [talk for talk in year_talks if talk.decision == decision]
            if not decision_talks:
                continue
            lines.extend(["", f"### {decision.title()}", ""])
            for index, talk in enumerate(sorted(decision_talks, key=lambda item: item.score, reverse=True)[:top_per_year], 1):
                speaker = _speaker_line(talk)
                lines.append(f"{index}. {talk.title}{speaker} - {talk.score:g}")
                lines.append(f"   - URL: {_presentation_url(talk)}")
                lines.append(f"   - Why: {talk.reason}")
                if talk.tags:
                    lines.append(f"   - Tags: {', '.join(talk.tags)}")

    return "\n".join(lines).rstrip() + "\n"


def render_weekly(talks: list[Talk], top: int = 10, report_date: date | None = None) -> str:
    """Render a compact weekly Markdown report for GitHub issue bodies."""
    today = report_date or date.today()
    selected = sorted(talks, key=lambda talk: talk.score, reverse=True)[:top]
    lines = [f"# InfoQ/QCon Weekly Watchlist: {today.isoformat()}", ""]
    for decision in DECISION_ORDER:
        decision_talks = [talk for talk in selected if talk.decision == decision]
        if not decision_talks:
            continue
        lines.extend([f"## {decision.title()}", ""])
        for index, talk in enumerate(decision_talks, 1):
            lines.append(f"{index}. [{talk.title}]({_presentation_url(talk)}) - {talk.score:g}")
            lines.append(f"   - Why: {talk.reason}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_issue_batch(talks: list[Talk], title: str) -> str:
    """Render GitHub issue-ready Markdown with review checkboxes."""
    lines = [f"# {title}", "", "Review queue:", ""]
    for talk in sorted(talks, key=lambda item: item.score, reverse=True):
        speaker = _speaker_line(talk)
        lines.append(f"- [ ] [{talk.title}]({_presentation_url(talk)}){speaker} - {talk.score:g} ({talk.decision})")
        lines.append(f"  - Why: {talk.reason}")
        if talk.tags:
            lines.append(f"  - Tags: {', '.join(talk.tags)}")
    return "\n".join(lines).rstrip() + "\n"


def _summary_lines(talks: list[Talk]) -> list[str]:
    """Build report totals that are cheap to validate in tests."""
    counts = {decision: 0 for decision in DECISION_ORDER}
    for talk in talks:
        counts[talk.decision] = counts.get(talk.decision, 0) + 1
    return [
        f"- total crawled: {len(talks)}",
        f"- total watch: {counts.get('watch', 0)}",
        f"- total skim: {counts.get('skim', 0)}",
        f"- total skipped: {counts.get('skip', 0)}",
        f"- date generated: {date.today().isoformat()}",
    ]


def _speaker_line(talk: Talk) -> str:
    """Format speaker/company metadata without adding awkward blanks."""
    bits = [bit for bit in [talk.speaker, talk.company] if bit]
    return f" - {', '.join(bits)}" if bits else ""


def _presentation_url(talk: Talk) -> str:
    """Use the canonical InfoQ presentation URL when available."""
    return talk.presentation_url or talk.url
