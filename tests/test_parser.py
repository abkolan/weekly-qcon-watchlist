from pathlib import Path

from infoq_watchlist.parser import parse_detail, parse_listing, parse_schedule_links


def test_parse_listing_extracts_static_card_metadata():
    html = Path("tests/fixtures/infoq_listing_with_pagination.html").read_text(encoding="utf-8")

    talks = parse_listing(html)

    # Static listing pages should be enough to seed the first database rows.
    assert len(talks) == 2
    assert talks[0].title == "Operating a Platform Control Plane at Scale"
    assert talks[0].url == "https://www.infoq.com/presentations/platform-control-plane/"
    assert talks[0].published_date.isoformat() == "2024-07-02"
    assert talks[0].year == 2024
    assert talks[0].speaker == "Priya Shah"
    assert talks[0].track == "Architecture & Design"
    assert talks[0].duration_minutes == 51
    assert talks[0].has_video is True
    assert talks[0].has_transcript is True


def test_parse_listing_skips_non_card_presentation_links():
    html = """
    <html>
      <body>
        <nav>
          <a href="/presentations/">Presentations</a>
          <a href="/presentations/2/">Older</a>
          <a href="https://feed.infoq.com/qcon-london-2016/presentations/">RSS Feed</a>
        </nav>
        <aside>
          <a href="/presentations/new-current-recommendation">Current recommendation</a>
        </aside>
        <li>
          <a href="/presentations/valid-talk">Valid Talk</a>
          <a href="/profile/Jane-Doe">Jane Doe</a>
          <span>on Jul 02, 2016</span>
          <span>Icon 42:09</span>
        </li>
      </body>
    </html>
    """

    talks = parse_listing(html)

    # Only dated/duration-bearing talk cards should seed the database.
    assert [talk.url for talk in talks] == ["https://www.infoq.com/presentations/valid-talk/"]


def test_parse_detail_merges_json_ld_and_page_flags():
    html = Path("tests/fixtures/infoq_detail.html").read_text(encoding="utf-8")

    talk = parse_detail(html, "https://www.infoq.com/presentations/platform-control-plane/")

    # JSON-LD should provide canonical detail metadata while page text provides asset flags.
    assert talk.title == "Operating a Platform Control Plane at Scale"
    assert talk.summary == "A practical walkthrough of operating platform APIs at scale."
    assert talk.published_date.isoformat() == "2024-07-02"
    assert talk.year == 2024
    assert talk.speaker == "Priya Shah, Mateo Chen"
    assert talk.duration_minutes == 51
    assert talk.has_video is True
    assert talk.has_slides is True
    assert talk.has_transcript is True


def test_parse_schedule_links_extracts_qcon_sf_talk_links():
    html = """
    <html>
      <body>
        <a href="/presentations/">Presentations</a>
        <a href="/presentations/slack-infrastructure/">How Slack Works Keith Adams</a>
        <a href="https://www.infoq.com/presentations/netflix-chaos-microservices?utm_source=infoq&utm_medium=QCon_EarlyAccessVideos&utm_campaign=QConSanFrancisco2016">Mastering Chaos</a>
      </body>
    </html>
    """

    talks = parse_schedule_links(html, base_url="https://www.infoq.com/conferences/qconsf2016/")

    # QCon SF schedule pages are not dated listing cards, but their talk links are useful seeds.
    assert [talk.presentation_url for talk in talks] == [
        "https://www.infoq.com/presentations/slack-infrastructure/",
        "https://www.infoq.com/presentations/netflix-chaos-microservices/",
    ]
    assert talks[0].conference == "QCon SF 2016"
    assert talks[0].year == 2016
