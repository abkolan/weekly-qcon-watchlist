from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("watchlist.toml")


@dataclass(frozen=True, slots=True)
class SignalConfig:
    """One weighted text signal loaded from the editable config."""

    name: str
    weight: float
    terms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WatchlistConfig:
    """Runtime scoring/backfill config with safe defaults."""

    default_start_year: int = 2016
    earliest_start_year: int = 2007
    thresholds: dict[str, float] = field(default_factory=lambda: {
        "watch": 16,
        "skim": 10,
        "transcript": 6,
        "background": 3,
    })
    metadata_weights: dict[str, float] = field(default_factory=lambda: {
        "qcon_source": 6,
        "relevant_track": 4,
        "has_transcript": 3,
        "has_video": 2,
        "has_slides": 1,
        "practical_duration": 1,
        "company_fit": 3,
        "recent_weekly": 2,
    })
    popularity: dict[str, int | bool] = field(default_factory=lambda: {
        "enabled": True,
        "like_step": 10,
        "view_step": 1000,
        "max_bonus": 4,
    })
    preferred_companies: tuple[str, ...] = ()
    qcon_seed_urls: tuple[str, ...] = ()
    github: dict[str, object] = field(default_factory=lambda: {
        "repo": "abkolan/weekly-qcon-watchlist",
        "project_owner": "abkolan",
        "project_title": "QCon Watch Backlog",
        "project_number": 0,
        "eligible_decisions": ["watch", "skim", "transcript"],
        "batch_limit": 25,
        "sleep_seconds": 1,
        "default_status": "Backlog",
    })
    signals: tuple[SignalConfig, ...] = ()


def load_config(path: str | Path | None = None) -> WatchlistConfig:
    """Load editable TOML config, falling back to built-in defaults."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return WatchlistConfig()

    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    backfill = raw.get("backfill", {})
    companies = raw.get("companies", {})
    sources = raw.get("sources", {})
    github = raw.get("github", {})
    signals = tuple(
        SignalConfig(
            name=str(item["name"]),
            weight=float(item["weight"]),
            terms=tuple(str(term) for term in item.get("terms", [])),
            tags=tuple(str(tag) for tag in item.get("tags", [])),
        )
        for item in raw.get("signals", [])
    )

    defaults = WatchlistConfig()
    return WatchlistConfig(
        default_start_year=int(backfill.get("default_start_year", defaults.default_start_year)),
        earliest_start_year=int(backfill.get("earliest_start_year", defaults.earliest_start_year)),
        thresholds={**defaults.thresholds, **raw.get("thresholds", {})},
        metadata_weights={**defaults.metadata_weights, **raw.get("metadata_weights", {})},
        popularity={**defaults.popularity, **raw.get("popularity", {})},
        preferred_companies=tuple(str(company) for company in companies.get("preferred", [])),
        qcon_seed_urls=tuple(str(url) for url in sources.get("qcon_seed_urls", defaults.qcon_seed_urls)),
        github={**defaults.github, **github},
        signals=signals or defaults.signals,
    )
