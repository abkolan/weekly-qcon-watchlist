from __future__ import annotations

import hashlib
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests


USER_AGENT = "weekly-qcon-watchlist/0.1 (+https://github.com/local/infoq-watchlist)"


def fetch_url(url: str, cache_dir: str | Path = "data/cache", timeout: int = 20, sleep_seconds: float = 0.5) -> str:
    """Fetch one URL politely and cache the HTML by URL hash."""
    cache_path = _cache_path(url, cache_dir)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(response.text, encoding="utf-8")
    time.sleep(sleep_seconds)
    return response.text


def read_fixture(path: str | Path) -> str:
    """Read local HTML so crawl behavior is testable before network usage."""
    return Path(path).read_text(encoding="utf-8")


def discover_listing_urls(seed_url: str, html: str, max_pages: int) -> list[str]:
    """Return seed plus static InfoQ pagination links, capped for polite crawls."""
    urls = [seed_url]
    seen = {seed_url.rstrip("/")}
    soup = BeautifulSoup(html, "html.parser")

    for link in soup.find_all("a", href=True):
        text = link.get_text(" ", strip=True).casefold()
        href = str(link["href"])
        if not _looks_like_pagination(text, href):
            continue
        url = urljoin(seed_url, href)
        key = url.rstrip("/")
        if key in seen:
            continue
        urls.append(url)
        seen.add(key)
        if len(urls) >= max_pages:
            break

    return urls[:max_pages]


def _looks_like_pagination(text: str, href: str) -> bool:
    """Recognize InfoQ older/newer and offset-style pagination links."""
    if text in {"older", "next", "more presentations"}:
        return True
    return bool("/presentations/" in href and href.rstrip("/").split("/")[-1].isdigit())


def _cache_path(url: str, cache_dir: str | Path) -> Path:
    """Map a URL to a stable cache filename."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return Path(cache_dir) / f"{digest}.html"
