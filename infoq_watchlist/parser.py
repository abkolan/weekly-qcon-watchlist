from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from infoq_watchlist.models import Talk


BASE_URL = "https://www.infoq.com"


def parse_listing(html: str, base_url: str = BASE_URL) -> list[Talk]:
    """Parse presentation links from static InfoQ listing HTML."""
    soup = BeautifulSoup(html, "html.parser")
    talks: list[Talk] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if not _looks_like_talk_href(href):
            continue
        url = _canonical_presentation_url(urljoin(base_url, href))
        if url in seen:
            continue
        title = anchor.get_text(" ", strip=True)
        if not title or title.lower() in {"view presentation", "presentation"}:
            continue

        container = _nearest_card(anchor)
        text = container.get_text(" ", strip=True) if container else anchor.get_text(" ", strip=True)
        published = _parse_visible_date(text)
        duration = _duration_minutes(text)
        if not published and duration is None:
            continue
        talks.append(
            Talk(
                url=url,
                presentation_url=url,
                title=title,
                summary=_summary_from_text(text, title),
                published_date=published,
                year=published.year if published else None,
                speaker=_speaker_from_container(container),
                duration_minutes=duration,
                source="InfoQ",
                conference=_conference_from_url(url),
                track=_track_from_container(container),
                has_video=duration is not None,
                has_transcript=_has_transcript_marker(container),
            )
        )
        seen.add(url)

    return talks


def parse_schedule_links(html: str, base_url: str = BASE_URL) -> list[Talk]:
    """Parse QCon schedule pages that link to talks without card dates."""
    soup = BeautifulSoup(html, "html.parser")
    talks: list[Talk] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if not _looks_like_talk_href(href):
            continue
        title = anchor.get_text(" ", strip=True)
        if not title or title.lower() in {"presentations", "view presentation"}:
            continue
        url = _canonical_presentation_url(urljoin(base_url, href))
        if url in seen:
            continue
        talks.append(
            Talk(
                url=url,
                presentation_url=url,
                title=title,
                year=_event_year_from_url(base_url) or _event_year_from_url(href),
                source="InfoQ",
                conference=_conference_from_url(base_url) or _conference_from_campaign(href),
            )
        )
        seen.add(url)

    return talks


def parse_detail(html: str, url: str) -> Talk:
    """Parse one InfoQ detail page using JSON-LD first and HTML fallbacks."""
    soup = BeautifulSoup(html, "html.parser")
    data = _json_ld(soup)
    title = str(data.get("name") or _first_text(soup, ["h1"]) or "Untitled")
    description = data.get("description") if isinstance(data.get("description"), str) else None
    published = _parse_date_value(data.get("datePublished"))
    author = data.get("author")

    return Talk(
        url=url,
        presentation_url=url,
        title=title,
        summary=description or _first_text(soup, ["meta[name='description']"]),
        published_date=published,
        year=published.year if published else None,
        speaker=_author_name(author),
        source="InfoQ",
        conference=_conference_from_url(url),
        duration_minutes=_iso_duration_minutes(data.get("duration")),
        has_video=bool(data.get("contentUrl") or soup.find("video") or "View Presentation" in soup.get_text(" ", strip=True)),
        has_slides="var slides" in html or "Download Slides" in html or "Slides" in soup.get_text(" ", strip=True),
        has_transcript=bool(soup.find(string=re.compile(r"^\s*Transcript\s*$", re.I))),
    )


def merge_detail(listing_talk: Talk, detail_talk: Talk) -> Talk:
    """Overlay richer detail-page fields onto listing metadata."""
    return replace(
        listing_talk,
        title=detail_talk.title or listing_talk.title,
        summary=detail_talk.summary or listing_talk.summary,
        published_date=detail_talk.published_date or listing_talk.published_date,
        year=detail_talk.year or listing_talk.year,
        speaker=detail_talk.speaker or listing_talk.speaker,
        duration_minutes=detail_talk.duration_minutes or listing_talk.duration_minutes,
        conference=detail_talk.conference or listing_talk.conference,
        has_video=listing_talk.has_video or detail_talk.has_video,
        has_slides=listing_talk.has_slides or detail_talk.has_slides,
        has_transcript=listing_talk.has_transcript or detail_talk.has_transcript,
    )


def _nearest_card(anchor) -> object | None:
    """Find a nearby list/card container that carries metadata around a title."""
    return anchor.find_parent(["article", "li", "div"])


def _looks_like_talk_href(href: str) -> bool:
    """Accept presentation detail URLs while skipping listing pagination URLs."""
    parsed = urlparse(href)
    path = parsed.path
    if "feed.infoq.com" in parsed.netloc:
        return False
    if "/presentations/" not in path:
        return False
    slug = path.rstrip("/").split("/")[-1]
    return bool(slug and not slug.isdigit() and slug != "presentations")


def _canonical_presentation_url(url: str) -> str:
    """Normalize InfoQ presentation URLs so slash variants dedupe."""
    parsed = urlparse(url)
    if parsed.netloc.endswith("infoq.com") and parsed.path.startswith("/presentations/"):
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/"
    return url


def _summary_from_text(text: str, title: str) -> str | None:
    """Use nearby card text as a lightweight summary when it has extra content."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned or cleaned == title:
        return None
    return cleaned[:500]


def _parse_visible_date(text: str):
    """Parse InfoQ visible dates such as 'on Jul 02, 2026'."""
    match = re.search(r"\bon\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", text)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%b %d, %Y").date()


def _duration_minutes(text: str) -> int | None:
    """Parse visible media durations like 50:41 into whole minutes."""
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    return minutes + (1 if seconds >= 30 else 0)


def _speaker_from_container(container) -> str | None:
    """Extract likely speaker names from profile links in a listing card."""
    if not container:
        return None
    names = [
        link.get_text(" ", strip=True)
        for link in container.find_all("a", href=True)
        if "/profile/" in str(link["href"]) and link.get_text(" ", strip=True)
    ]
    return ", ".join(dict.fromkeys(names)) or None


def _track_from_container(container) -> str | None:
    """Extract common InfoQ track/topic links from a listing card."""
    if not container:
        return None
    for link in container.find_all("a", href=True):
        text = link.get_text(" ", strip=True)
        if text in {"Architecture & Design", "DevOps", "AI, ML & Data Engineering", "Development", "Culture & Methods"}:
            return text
    return None


def _has_transcript_marker(container) -> bool:
    """Detect transcript hints on either the card itself or its children."""
    if not container:
        return False
    return bool(container.has_attr("data-transcript") or container.find(attrs={"data-transcript": True}))


def _conference_from_url(url: str) -> str | None:
    """Infer broad conference source from URL slugs."""
    match = re.search(r"/(qcon[^/]+)/", url)
    if not match:
        match = re.search(r"/conferences/(qcon[^/]+)/", url)
    return _format_qcon_slug(match.group(1)) if match else None


def _event_year_from_url(url: str) -> int | None:
    """Infer event year from QCon archive URLs such as qconsf2016."""
    match = re.search(r"(?:qcon[^/]*?)(20\d{2})", url, re.I)
    return int(match.group(1)) if match else None


def _conference_from_campaign(href: str) -> str | None:
    """Infer conference names from old QCon schedule tracking parameters."""
    match = re.search(r"QCon([A-Za-z]+)(\d{4})", href)
    if not match:
        return None
    city = match.group(1)
    year = match.group(2)
    if city.casefold() == "sanfrancisco":
        city = "San Francisco"
    return f"QCon {city} {year}"


def _format_qcon_slug(slug: str) -> str:
    """Format QCon archive slugs into readable conference names."""
    year_match = re.search(r"(20\d{2})", slug)
    year = year_match.group(1) if year_match else ""
    normalized = slug.lower().replace("-", " ")
    if "sf" in normalized or "san francisco" in normalized:
        city = "SF"
    elif "newyork" in normalized or "new york" in normalized:
        city = "New York"
    elif "london" in normalized:
        city = "London"
    else:
        city = normalized.replace("qcon", "").strip().title()
    return " ".join(part for part in ["QCon", city, year] if part)


def _json_ld(soup: BeautifulSoup) -> dict:
    """Return the first JSON-LD object on a detail page."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            parsed = json.loads(script.string or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    """Read the first matching selector as plain text or content attr."""
    for selector in selectors:
        element = soup.select_one(selector)
        if not element:
            continue
        if element.name == "meta":
            return element.get("content")
        return element.get_text(" ", strip=True)
    return None


def _parse_date_value(value: object):
    """Parse JSON-LD date values when present."""
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value[:10]).date()


def _author_name(author: object) -> str | None:
    """Normalize JSON-LD author structures into a display string."""
    if isinstance(author, dict):
        return author.get("name")
    if isinstance(author, list):
        names = [item.get("name") for item in author if isinstance(item, dict) and item.get("name")]
        return ", ".join(names) or None
    return None


def _iso_duration_minutes(value: object) -> int | None:
    """Parse basic ISO-8601 durations like PT50M41S."""
    if not isinstance(value, str):
        return None
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 60 + minutes + (1 if seconds >= 30 else 0)
