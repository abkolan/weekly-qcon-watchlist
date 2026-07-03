from __future__ import annotations

import re
from dataclasses import replace

from infoq_watchlist.config import WatchlistConfig
from infoq_watchlist.models import Talk


def score_talk(talk: Talk, config: WatchlistConfig) -> Talk:
    """Score one talk with deterministic metadata and text signals."""
    score = 0.0
    reasons: list[str] = []
    tags: set[str] = set(talk.tags)

    searchable = _searchable_text(talk)

    # Metadata signals are explicit and cheap to explain in the generated report.
    score += _score_metadata(talk, config, reasons, tags)

    for signal in config.signals:
        matches = _matching_terms(searchable, signal.terms)
        if not matches:
            continue
        score += signal.weight
        tags.update(signal.tags or (signal.name,))
        reasons.append(f"{signal.name}: {', '.join(matches[:3])}")

    decision = _decision_for_score(score, config.thresholds)
    return replace(
        talk,
        score=score,
        decision=decision,
        reason="; ".join(reasons) if reasons else "No strong configured signals matched",
        tags=sorted(tags),
    )


def _score_metadata(
    talk: Talk,
    config: WatchlistConfig,
    reasons: list[str],
    tags: set[str],
) -> float:
    """Apply non-text signals that are stable enough for v1 ranking."""
    score = 0.0
    weights = config.metadata_weights

    if _contains_any([talk.source, talk.conference, talk.url], ["qcon"]):
        score += float(weights.get("qcon_source", 0))
        tags.add("qcon")
        reasons.append("QCon source")

    if _contains_any([talk.track, *talk.topics], ["architecture", "devops", "data", "ai", "platform", "sre"]):
        score += float(weights.get("relevant_track", 0))
        tags.add("relevant-track")
        reasons.append("relevant track/topic metadata")

    if talk.has_transcript:
        score += float(weights.get("has_transcript", 0))
        reasons.append("has transcript")

    if talk.has_video:
        score += float(weights.get("has_video", 0))
        reasons.append("has video")

    if talk.has_slides:
        score += float(weights.get("has_slides", 0))
        reasons.append("has slides")

    if talk.duration_minutes is not None and 25 <= talk.duration_minutes <= 70:
        score += float(weights.get("practical_duration", 0))
        reasons.append("practical duration")

    company_text = (talk.company or "").casefold()
    preferred = [company.casefold() for company in config.preferred_companies]
    if company_text and any(company in company_text for company in preferred):
        score += float(weights.get("company_fit", 0))
        tags.add("company-fit")
        reasons.append("preferred company")

    score += _popularity_bonus(talk, config, reasons)
    return score


def _popularity_bonus(talk: Talk, config: WatchlistConfig, reasons: list[str]) -> float:
    """Use popularity only when static HTML exposes stable counters."""
    popularity = config.popularity
    if not popularity.get("enabled", True):
        return 0.0

    max_bonus = int(popularity.get("max_bonus", 4))
    like_step = int(popularity.get("like_step", 10))
    view_step = int(popularity.get("view_step", 1000))
    bonus = 0

    if talk.like_count is not None and like_step > 0:
        bonus += talk.like_count // like_step
    if talk.view_count is not None and view_step > 0:
        bonus += talk.view_count // view_step

    bonus = min(max_bonus, bonus)
    if bonus:
        reasons.append(f"popularity +{bonus}")
    return float(bonus)


def _searchable_text(talk: Talk) -> str:
    """Join all human text fields so term matching stays simple."""
    parts = [
        talk.title,
        talk.summary or "",
        talk.speaker or "",
        talk.company or "",
        talk.source or "",
        talk.conference or "",
        talk.track or "",
        " ".join(talk.topics),
    ]
    return " ".join(parts).casefold()


def _matching_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    """Return configured terms that appear as case-insensitive phrases."""
    matches: list[str] = []
    for term in terms:
        normalized = term.casefold()
        pattern = r"(?<!\w)" + re.escape(normalized) + r"(?!\w)"
        if re.search(pattern, text):
            matches.append(term)
    return matches


def _contains_any(values: list[str | None], needles: list[str]) -> bool:
    """Check simple substring matches across optional metadata values."""
    text = " ".join(value or "" for value in values).casefold()
    return any(needle.casefold() in text for needle in needles)


def _decision_for_score(score: float, thresholds: dict[str, float]) -> str:
    """Map numeric scores to the configured reading decision."""
    if score >= float(thresholds["watch"]):
        return "watch"
    if score >= float(thresholds["skim"]):
        return "skim"
    if score >= float(thresholds["transcript"]):
        return "transcript"
    if score >= float(thresholds["background"]):
        return "background"
    return "skip"
