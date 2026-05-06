import pytest
from unittest.mock import patch, MagicMock
from agents.discovery.reddit_scraper import RedditScraper, RedditPost


@pytest.fixture
def scraper():
    return RedditScraper()


def _mock_rss_response(entries_xml: str) -> MagicMock:
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  {entries_xml}
</feed>"""
    resp = MagicMock()
    resp.status_code = 200
    resp.text = rss
    resp.raise_for_status.return_value = None
    return resp


def test_fetch_top_posts_returns_posts(scraper):
    entries = """
    <entry>
      <id>t3_abc</id>
      <link href="https://www.reddit.com/r/legaladvice/comments/abc/i_won/"/>
      <title>I won a lawsuit</title>
      <summary>Long enough body that passes the minimum length requirement. This text is intentionally padded to exceed 300 characters so that fetch_top_posts includes it in the returned results. Adding more words here to make absolutely sure we are well above the 300 character threshold and this entry appears in the output list.</summary>
    </entry>
    <entry>
      <id>t3_def</id>
      <link href="https://www.reddit.com/r/legaladvice/comments/def/short/"/>
      <title>Short post</title>
      <summary>short</summary>
    </entry>
    """
    with patch("requests.get", return_value=_mock_rss_response(entries)):
        result = scraper.fetch_top_posts("legaladvice", min_body_length=300, limit=10)
    assert len(result) == 1
    assert result[0].post_id == "abc"


def test_fetch_top_posts_filters_short_body(scraper):
    entries = """
    <entry>
      <id>t3_short</id>
      <link href="https://www.reddit.com/r/legaladvice/comments/short/title/"/>
      <title>Short post</title>
      <summary>too short</summary>
    </entry>
    """
    with patch("requests.get", return_value=_mock_rss_response(entries)):
        result = scraper.fetch_top_posts("legaladvice", min_body_length=300, limit=10)
    assert result == []


def test_deduplicate_removes_known_ids(scraper):
    posts = [
        RedditPost(post_id="known", title="Old", body="x" * 400, score=0, url="http://x.com", subreddit="legal"),
        RedditPost(post_id="new", title="New", body="x" * 400, score=0, url="http://y.com", subreddit="legal"),
    ]
    result = scraper.deduplicate(posts, known_ids={"known"})
    assert len(result) == 1
    assert result[0].post_id == "new"
