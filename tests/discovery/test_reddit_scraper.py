import pytest
from unittest.mock import patch, MagicMock
from agents.discovery.reddit_scraper import RedditScraper, RedditPost


@pytest.fixture
def scraper():
    return RedditScraper()


def _mock_reddit_response(posts: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "data": {
            "children": [
                {"data": p} for p in posts
            ]
        }
    }
    return resp


def test_fetch_top_posts_returns_posts(scraper):
    posts = [
        {"id": "abc", "title": "I won a lawsuit", "selftext": "x" * 400, "score": 1200, "url": "https://reddit.com/abc", "permalink": "/r/legaladvice/abc"},
        {"id": "def", "title": "Short post", "selftext": "short", "score": 800, "url": "https://reddit.com/def", "permalink": "/r/legaladvice/def"},
    ]
    with patch("requests.get", return_value=_mock_reddit_response(posts)):
        result = scraper.fetch_top_posts("legaladvice", min_score=500, min_body_length=300, limit=10)
    assert len(result) == 1  # "Short post" filtered out
    assert result[0].post_id == "abc"


def test_fetch_top_posts_filters_low_score(scraper):
    posts = [
        {"id": "low", "title": "Low score post", "selftext": "x" * 400, "score": 50, "url": "http://x.com", "permalink": "/r/x/low"},
    ]
    with patch("requests.get", return_value=_mock_reddit_response(posts)):
        result = scraper.fetch_top_posts("legaladvice", min_score=500, min_body_length=300, limit=10)
    assert result == []


def test_deduplicate_removes_known_ids(scraper):
    posts = [
        RedditPost(post_id="known", title="Old", body="x" * 400, score=900, url="http://x.com", subreddit="legal"),
        RedditPost(post_id="new", title="New", body="x" * 400, score=900, url="http://y.com", subreddit="legal"),
    ]
    result = scraper.deduplicate(posts, known_ids={"known"})
    assert len(result) == 1
    assert result[0].post_id == "new"
