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


def test_news_scraper_raises_on_zero_articles():
    from agents.discovery.news_scraper import NewsScraper
    from datetime import datetime, timezone

    failing_adapter = MagicMock()
    failing_adapter.fetch.return_value = []

    with patch("agents.discovery.news_scraper.execute_with_retry") as mock_db:
        mock_db.side_effect = [
            MagicMock(data=[{"id": "niche-1", "category": "legal", "name": "Legal Advice"}]),
            MagicMock(data=[]),
        ]
        scraper = NewsScraper(
            supabase=MagicMock(),
            gate_client=MagicMock(),
            adapters=[failing_adapter],
            news_keywords={"legal": ["lawsuit settlement"]},
        )
        with pytest.raises(RuntimeError, match="zero articles fetched"):
            scraper.run()


def test_news_scraper_inserts_high_scoring_topics():
    from agents.discovery.news_scraper import NewsScraper, NewsItem
    from datetime import datetime, timezone

    item = NewsItem(
        source_type="google_news",
        source_id="abc123",
        title="Major lawsuit settled",
        url="https://example.com/article",
        published_at=datetime(2025, 5, 7, 10, 0, tzinfo=timezone.utc),
        keywords_matched=["lawsuit settlement"],
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [item]

    with patch("agents.discovery.news_scraper.execute_with_retry") as mock_db:
        mock_db.side_effect = [
            MagicMock(data=[{"id": "niche-1", "category": "legal", "name": "Legal Advice"}]),
            MagicMock(data=[]),
            MagicMock(data=[{"id": "topic-new"}]),
            MagicMock(data=[{}]),
        ]
        scraper = NewsScraper(
            supabase=MagicMock(),
            gate_client=MagicMock(),
            adapters=[mock_adapter],
            news_keywords={"legal": ["lawsuit settlement"]},
        )
        with patch.object(scraper, "_score_item", return_value=8.0):
            scraper.run()

    # Verify at least 3 DB calls: niches, known_pairs, insert
    assert mock_db.call_count >= 3
