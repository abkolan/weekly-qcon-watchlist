from pathlib import Path

from infoq_watchlist import crawler


def test_discover_listing_urls_returns_seed_and_pagination_links_capped():
    html = Path("tests/fixtures/infoq_listing_with_pagination.html").read_text(encoding="utf-8")
    seed_url = "https://www.infoq.com/presentations/"

    urls = crawler.discover_listing_urls(seed_url, html, max_pages=3)

    # The crawler should preserve crawl order and normalize relative pagination URLs.
    assert urls == [
        seed_url,
        "https://www.infoq.com/presentations/2/",
        "https://www.infoq.com/presentations/3/",
    ]


def test_discover_listing_urls_respects_max_pages_for_seed_only():
    html = Path("tests/fixtures/infoq_listing_with_pagination.html").read_text(encoding="utf-8")

    urls = crawler.discover_listing_urls("https://www.infoq.com/presentations/", html, max_pages=1)

    # max_pages is a total page cap, so page discovery stops after the seed URL.
    assert urls == ["https://www.infoq.com/presentations/"]
