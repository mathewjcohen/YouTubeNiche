import hashlib
import json
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


def test_newsapi_adapter_parses_fixture():
    from agents.discovery.news_scraper import NewsAPIAdapter, NewsItem

    fixture = json.loads((FIXTURES_DIR / "newsapi_response.json").read_text())

    with patch("agents.discovery.news_scraper.requests.get") as mock_get:
        mock_get.return_value.json.return_value = fixture
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.status_code = 200
        items = NewsAPIAdapter(api_key="test_key").fetch("insurance claim denied", days=9999)

    assert len(items) == 2
    assert all(isinstance(i, NewsItem) for i in items)
    assert items[0].source_type == "newsapi"
    assert items[0].source_id == "https://newsapi.example.com/articles/insurance-claim-denied-1"
    assert items[0].title == "Insurance claim denied after hurricane damage"
    assert items[0].keywords_matched == ["insurance claim denied"]
