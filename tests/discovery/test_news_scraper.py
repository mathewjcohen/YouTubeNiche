import hashlib
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_GOOD_BODY = "x" * 300  # 300 chars — passes the MIN_BODY_CHARS=200 check


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

    failing_adapter = MagicMock()
    failing_adapter.fetch.return_value = []

    with patch("agents.discovery.news_scraper.execute_with_retry") as mock_db:
        mock_db.side_effect = [
            MagicMock(data=[{"id": "niche-1", "category": "legal", "name": "Legal Advice"}]),
            MagicMock(data=[]),   # known_pairs
            MagicMock(data=[]),   # recent_titles for niche-1
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
            MagicMock(data=[]),   # known_pairs
            MagicMock(data=[]),   # recent_titles for niche-1
            MagicMock(data=[{"id": "topic-new"}]),  # insert
            MagicMock(data=[{}]),                   # app_settings upsert
        ]
        scraper = NewsScraper(
            supabase=MagicMock(),
            gate_client=MagicMock(),
            adapters=[mock_adapter],
            news_keywords={"legal": ["lawsuit settlement"]},
        )
        with patch.object(scraper, "_score_item", return_value=8.0):
            with patch("agents.discovery.news_scraper.fetch_article_body", return_value=_GOOD_BODY):
                scraper.run()

    # niches, known_pairs, recent_titles, insert, app_settings upsert
    assert mock_db.call_count >= 4


def test_news_scraper_skips_thin_body():
    from agents.discovery.news_scraper import NewsScraper, NewsItem
    from datetime import datetime, timezone

    item = NewsItem(
        source_type="google_news",
        source_id="abc999",
        title="Story with no article body",
        url="https://example.com/paywalled",
        published_at=datetime(2025, 5, 7, 10, 0, tzinfo=timezone.utc),
        keywords_matched=["lawsuit"],
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [item]

    with patch("agents.discovery.news_scraper.execute_with_retry") as mock_db:
        mock_db.side_effect = [
            MagicMock(data=[{"id": "niche-1", "category": "legal", "name": "Legal Advice"}]),
            MagicMock(data=[]),   # known_pairs
            MagicMock(data=[]),   # recent_titles
            MagicMock(data=[{}]), # app_settings upsert
        ]
        scraper = NewsScraper(
            supabase=MagicMock(),
            gate_client=MagicMock(),
            adapters=[mock_adapter],
            news_keywords={"legal": ["lawsuit"]},
        )
        with patch.object(scraper, "_score_item", return_value=8.0):
            with patch("agents.discovery.news_scraper.fetch_article_body", return_value="Too short"):
                scraper.run()

    # No insert should have happened — call count stays at niches+known+recent+upsert
    call_tables = [str(c) for c in mock_db.call_args_list]
    assert not any("insert" in t.lower() for t in call_tables)


def test_news_scraper_deduplicates_similar_titles():
    from agents.discovery.news_scraper import NewsScraper, NewsItem
    from datetime import datetime, timezone

    existing_title = "Hantavirus Outbreak on Cruise Ship"
    duplicate_title = "Cruise Ship Hantavirus Cases Rising"

    item = NewsItem(
        source_type="google_news",
        source_id="dup999",
        title=duplicate_title,
        url="https://example.com/dup-story",
        published_at=datetime(2025, 5, 8, 10, 0, tzinfo=timezone.utc),
        keywords_matched=["hantavirus"],
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [item]

    with patch("agents.discovery.news_scraper.execute_with_retry") as mock_db:
        mock_db.side_effect = [
            MagicMock(data=[{"id": "niche-1", "category": "health", "name": "Health"}]),
            MagicMock(data=[]),                            # known_pairs
            MagicMock(data=[{"title": existing_title}]),   # recent_titles — has the original story
            MagicMock(data=[{}]),                          # app_settings upsert
        ]
        scraper = NewsScraper(
            supabase=MagicMock(),
            gate_client=MagicMock(),
            adapters=[mock_adapter],
            news_keywords={"health": ["hantavirus"]},
        )
        with patch.object(scraper, "_score_item", return_value=8.0):
            with patch("agents.discovery.news_scraper.fetch_article_body", return_value=_GOOD_BODY):
                scraper.run()

    # No insert — the duplicate was rejected
    call_tables = [str(c) for c in mock_db.call_args_list]
    assert not any("insert" in t.lower() for t in call_tables)


def test_title_tokens_filters_stopwords():
    from agents.discovery.news_scraper import _title_tokens

    tokens = _title_tokens("A family in Texas was sued for the first time")
    assert "family" in tokens
    assert "texas" in tokens
    assert "sued" in tokens
    # stopwords stripped
    assert "a" not in tokens
    assert "in" not in tokens
    assert "the" not in tokens
    assert "for" not in tokens


def test_jaccard_dedup_threshold():
    from agents.discovery.news_scraper import _title_tokens, _jaccard, _DEDUP_THRESHOLD

    a = _title_tokens("Hantavirus Outbreak on Cruise Ship")
    b = _title_tokens("Cruise Ship Hantavirus Cases Rising")
    assert _jaccard(a, b) >= _DEDUP_THRESHOLD

    c = _title_tokens("Man sues Tesla over autopilot crash")
    d = _title_tokens("Hurricane destroys beachfront homes in Florida")
    assert _jaccard(c, d) < _DEDUP_THRESHOLD


def test_main_exits_early_when_paused(capsys):
    """main() should print a pause message and return without running the scraper."""
    from agents.discovery.news_scraper import main

    with patch("supabase.create_client") as mock_create, \
         patch("agents.discovery.news_scraper.patch_postgrest_http1") as mock_patch, \
         patch("agents.discovery.news_scraper.GateClient"), \
         patch("agents.discovery.news_scraper.NewsScraper") as mock_scraper_cls, \
         patch.dict("os.environ", {"SUPABASE_URL": "http://x", "SUPABASE_SERVICE_KEY": "key"}):

        mock_sb = MagicMock()
        mock_create.return_value = mock_sb
        mock_patch.return_value = mock_sb

        # Simulate app_settings returning topic_runner_enabled=false
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"value": "false"}
        ]

        main()

    mock_scraper_cls.return_value.run.assert_not_called()
    captured = capsys.readouterr()
    assert "paused" in captured.out


# ---------------------------------------------------------------------------
# Test: _load_content_patterns() returns None when no insights exist
# ---------------------------------------------------------------------------
def test_load_content_patterns_returns_none_when_empty():
    from agents.discovery.news_scraper import NewsScraper

    scraper = NewsScraper.__new__(NewsScraper)
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value.data = []
    scraper._sb = mock_sb

    result = scraper._load_content_patterns()
    assert result is None


# ---------------------------------------------------------------------------
# Test: _load_content_patterns() returns patterns when insights exist
# ---------------------------------------------------------------------------
def test_load_content_patterns_returns_patterns():
    from agents.discovery.news_scraper import NewsScraper

    scraper = NewsScraper.__new__(NewsScraper)
    mock_sb = MagicMock()
    patterns = {"winning_angles": ["Personal-stakes finance"], "avoid": ["Curiosity-gap hooks"]}
    mock_sb.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"stats_json": {"content_patterns": patterns}}
    ]
    scraper._sb = mock_sb

    result = scraper._load_content_patterns()
    assert result == patterns
    assert result["winning_angles"] == ["Personal-stakes finance"]


# ---------------------------------------------------------------------------
# Test: _score_item() prompt includes pattern context when patterns available
# ---------------------------------------------------------------------------
def test_score_item_injects_patterns_into_prompt():
    from agents.discovery.news_scraper import NewsScraper, NewsItem
    from datetime import datetime, timezone

    scraper = NewsScraper.__new__(NewsScraper)
    scraper._content_patterns = {
        "winning_angles": ["Personal-stakes finance"],
        "avoid": ["Curiosity-gap hooks"]
    }

    captured_prompt = []

    def fake_complete(prompt, **kwargs):
        captured_prompt.append(prompt)
        return "8"

    item = NewsItem(
        source_type="google_news",
        source_id="x",
        title="How Rising Rent Is Crushing Middle-Class Families",
        url="https://example.com",
        published_at=datetime(2025, 5, 7, 10, 0, tzinfo=timezone.utc),
        keywords_matched=[],
    )

    with patch("agents.shared.anthropic_client.complete", side_effect=fake_complete):
        scraper._score_item(item, "personal finance", "Finance Channel")

    assert "Personal-stakes finance" in captured_prompt[0]
    assert "Curiosity-gap hooks" in captured_prompt[0]
