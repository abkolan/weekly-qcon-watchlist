from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone


Decision = str


@dataclass(slots=True)
class Talk:
    """Structured metadata and scoring state for one InfoQ/QCon talk."""

    url: str
    title: str
    presentation_url: str | None = None
    summary: str | None = None
    published_date: date | None = None
    year: int | None = None
    conference_year: int | None = None
    speaker: str | None = None
    company: str | None = None
    duration_minutes: int | None = None
    source: str | None = None
    conference: str | None = None
    track: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    topics: list[str] = field(default_factory=list)
    has_video: bool = False
    has_slides: bool = False
    has_transcript: bool = False
    score: float = 0.0
    decision: Decision = "skip"
    reason: str = ""
    tags: list[str] = field(default_factory=list)
    fetched_at: datetime | None = None
    updated_at: datetime | None = None

    def with_timestamps(self) -> Talk:
        """Return a copy with missing timestamps filled for storage."""
        now = datetime.now(timezone.utc)
        return replace(
            self,
            # Store a direct InfoQ presentation link even if future crawl IDs differ.
            presentation_url=self.presentation_url or self.url,
            fetched_at=self.fetched_at or now,
            updated_at=now,
            year=self.year or (self.published_date.year if self.published_date else None),
        )
