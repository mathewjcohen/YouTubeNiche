import hashlib
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_google_news_adapter_parses_fixture():
    import feedparser
    from agents.discovery.news_scraper import GoogleNewsAdapter, NewsItem

    xml = (FIXTURES_DIR / "google_news_response.xml").read_text()
    real_feed = feedparser.parse(xml)

    with patch("agents.discovery.news_scraper.feedparser.parse", return_value=real_feed):
        items = GoogleNewsAdapter().fetch("lawsuit settlement", days=9999)

    assert len(items) == 2
    assert all(isinstance(i, NewsItem) for i in items)
    assert items[0].source_type == "google_news"
    assert items[0].title == "Lawsuit settlement reached in major class action case"
    expected_id = hashlib.sha256(b"https://news.example.com/article/lawsuit-settlement-2025").hexdigest()
    assert items[0].source_id == expected_id
    assert items[0].keywords_matched == ["lawsuit settlement"]
