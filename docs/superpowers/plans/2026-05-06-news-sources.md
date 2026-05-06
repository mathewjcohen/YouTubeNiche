# News Sources & Niche Scout Extension — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pluggable news adapters (Google News RSS + NewsAPI) to feed timely topics into the pipeline, and extend the Niche Scout to discover new niches from high-velocity news clusters while scoring all candidates against a news velocity signal.

**Architecture:** A `NewsScraper` orchestrator in `agents/discovery/news_scraper.py` follows the same per-niche iteration pattern as `reddit_scraper.py`, using a `NewsAdapter` Protocol for swappable sources. `NicheScorer` gains a `news_velocity()` method and a `news_score` field on its result. `NicheScout.run()` gains a second pass that treats keywords with ≥5 articles in 48h as niche candidates.

**Tech Stack:** Python 3.10+, Pydantic v2 (NewsItem validation), feedparser (Google News RSS), requests (NewsAPI), GitHub Actions (daily cron), Supabase (topics table).

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `migrations/007_topics_source_type.sql` | Add source_type/source_id, relax reddit_post_id constraint |
| Modify | `agents/discovery/reddit_scraper.py` | Write source_type/source_id on insert, load known_ids by source_type |
| Create | `agents/discovery/news_scraper.py` | NewsItem, NewsAdapter Protocol, GoogleNewsAdapter, NewsAPIAdapter, NewsScraper, main() |
| Create | `config/news_keywords.json` | Keyword lists per category (mirrors subreddits.json keys) |
| Create | `.github/workflows/news_scraper.yml` | Daily cron at 06:00 UTC |
| Modify | `agents/discovery/niche_scorer.py` | news_score field on NicheScoreResult, news_adapters param, news_velocity() method |
| Modify | `agents/discovery/niche_scout.py` | News discovery pass + news_adapters injection |
| Create | `tests/discovery/fixtures/google_news_response.xml` | Google News RSS fixture |
| Create | `tests/discovery/fixtures/newsapi_response.json` | NewsAPI JSON fixture |
| Create | `tests/discovery/test_news_scraper.py` | Adapter parse tests, NewsScraper zero-articles test |
| Modify | `tests/discovery/test_niche_scorer.py` | news_velocity tests |
| Modify | `tests/discovery/test_niche_scout.py` | News discovery pass test |
| Modify | `requirements.txt` | Add pydantic>=2.0.0 |

---

### Task 1: Schema migration and reddit_scraper source columns

**Files:**
- Create: `migrations/007_topics_source_type.sql`
- Modify: `agents/discovery/reddit_scraper.py` (`main()` function only — lines 98–153)

- [ ] **Step 1: Write the migration**

Create `migrations/007_topics_source_type.sql`:

```sql
-- Add source_type and source_id to topics
ALTER TABLE topics
  ADD COLUMN source_type text NOT NULL DEFAULT 'reddit',
  ADD COLUMN source_id   text;

-- Backfill source_id from reddit_post_id
UPDATE topics
   SET source_id = reddit_post_id
 WHERE reddit_post_id IS NOT NULL;

-- Drop old unique constraint (was: UNIQUE(reddit_post_id))
ALTER TABLE topics
  DROP CONSTRAINT IF EXISTS topics_reddit_post_id_key;

-- Make reddit_post_id nullable (deprecated, retained for read compat)
ALTER TABLE topics
  ALTER COLUMN reddit_post_id DROP NOT NULL;

-- New composite unique constraint
ALTER TABLE topics
  ADD CONSTRAINT topics_source_type_source_id_key UNIQUE (source_type, source_id);
```

- [ ] **Step 2: Apply the migration in Supabase**

Run: open Supabase dashboard → SQL editor → paste and execute the migration file.

Expected: command completes with no errors; `topics` table now has `source_type` (default `'reddit'`) and `source_id` columns.

- [ ] **Step 3: Update reddit_scraper.py to write source columns**

In `agents/discovery/reddit_scraper.py`, change the `main()` function (leave the `RedditScraper` class unchanged):

```python
def main():
    from supabase import create_client
    from agents.shared.config_loader import get_env, get_subreddits
    from agents.shared.anthropic_client import complete
    from agents.shared.gate_client import GateClient, GateNumber
    from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1

    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    gate = GateClient(sb)
    scraper = RedditScraper()
    subreddits_map = get_subreddits()

    active_niches = execute_with_retry(sb.table("niches").select("*").in_("status", ["testing", "promoted"])).data
    # Load known source_ids for reddit posts only (source_type = 'reddit')
    known_ids = {
        row["source_id"]
        for row in execute_with_retry(
            sb.table("topics").select("source_id").eq("source_type", "reddit")
        ).data
        if row.get("source_id")
    }

    for niche in active_niches:
        subs = niche.get("subreddits") or subreddits_map.get(niche["category"], [])
        posts = scraper.fetch_all_for_niche(subs)
        print(f"[reddit] {niche['name']}: {len(posts)} posts before dedup")
        posts = scraper.deduplicate(posts, known_ids)
        print(f"[reddit] {niche['name']}: {len(posts)} posts after dedup, processing up to 25")
        for post in posts[:25]:
            score_prompt = (
                f"Rate this Reddit post for YouTube video potential. Score 1-10 using these criteria:\n"
                f"- Clear story arc with conflict and resolution (not just a question or rant)\n"
                f"- Outcome is surprising, instructive, or emotionally compelling\n"
                f"- General audience would care, not just niche Reddit insiders\n"
                f"- Enough detail to sustain a 10-12 minute video\n"
                f"- Evergreen (not a breaking news moment that expires in days)\n\n"
                f"Title: {post.title}\n"
                f"Body excerpt: {post.body[:300]}\n\n"
                f"Return only the integer score."
            )
            try:
                score_str = complete(score_prompt, model="claude-haiku-4-5-20251001", max_tokens=10)
                claude_score = float(score_str.strip())
            except Exception:
                claude_score = 5.0

            if claude_score < 6:
                print(f"[reddit] skipped (score {claude_score}): {post.title[:60]}")
                continue

            result = execute_with_retry(sb.table("topics").insert({
                "niche_id": niche["id"],
                "reddit_post_id": post.post_id,   # retained for compat
                "source_type": "reddit",
                "source_id": post.post_id,
                "title": post.title,
                "url": post.url,
                "body": post.body,
                "upvotes": post.score,
                "claude_score": claude_score,
                "status": "pending",
                "gate2_state": "pending",
            }))
            if not result.data:
                print(f"[reddit] insert returned no data for post {post.post_id}, skip")
                continue
            topic_id = result.data[0]["id"]
            gate.advance_or_pause(
                gate=GateNumber.TOPIC_SELECTION,
                niche_id=niche["id"],
                table="topics",
                item_id=topic_id,
                gate_column="gate2_state",
                auto_state="approved",
                review_state="awaiting_review",
            )
            known_ids.add(post.post_id)
    print(f"[reddit-scraper] done for {len(active_niches)} active niches")
```

- [ ] **Step 4: Run existing reddit_scraper tests to verify nothing broke**

Run: `cd /Users/maco/Documents/ClaudeVault/projects/YouTubeNiche && python3 -m pytest tests/discovery/test_reddit_scraper.py -v`

Expected:
```
test_fetch_top_posts_returns_posts PASSED
test_fetch_top_posts_filters_low_score PASSED
test_deduplicate_removes_known_ids PASSED
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add migrations/007_topics_source_type.sql agents/discovery/reddit_scraper.py
git commit -m "feat: add source_type/source_id to topics; update reddit_scraper to write them"
```

---

### Task 2: NewsItem, NewsAdapter Protocol, and GoogleNewsAdapter

**Files:**
- Create: `agents/discovery/news_scraper.py`
- Create: `tests/discovery/fixtures/google_news_response.xml`
- Create: `tests/discovery/test_news_scraper.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write the failing test for GoogleNewsAdapter**

Create `tests/discovery/fixtures/` directory and `tests/discovery/fixtures/google_news_response.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News - lawsuit settlement</title>
    <link>https://news.google.com</link>
    <item>
      <title>Lawsuit settlement reached in major class action case</title>
      <link>https://news.example.com/article/lawsuit-settlement-2025</link>
      <pubDate>Wed, 07 May 2025 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Court ruling changes consumer rights nationwide</title>
      <link>https://news.example.com/article/court-ruling-consumer-rights</link>
      <pubDate>Wed, 07 May 2025 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
```

Create `tests/discovery/test_news_scraper.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/discovery/test_news_scraper.py::test_google_news_adapter_parses_fixture -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.discovery.news_scraper'`

- [ ] **Step 3: Add pydantic to requirements.txt**

In `requirements.txt`, add after the first line (`anthropic>=0.25.0`):

```
pydantic>=2.0.0
```

Install: `pip3 install pydantic>=2.0.0`

- [ ] **Step 4: Create agents/discovery/news_scraper.py with NewsItem, NewsAdapter, GoogleNewsAdapter**

Create `agents/discovery/news_scraper.py`:

```python
import hashlib
import os
import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Protocol

import feedparser
import requests
from pydantic import BaseModel


class NewsItem(BaseModel):
    source_type: str
    source_id: str
    title: str
    url: str
    published_at: datetime
    keywords_matched: list[str]


class NewsAdapter(Protocol):
    def fetch(self, keyword: str, days: int = 2) -> list[NewsItem]: ...


class GoogleNewsAdapter:
    def fetch(self, keyword: str, days: int = 2) -> list[NewsItem]:
        url = f"https://news.google.com/rss/search?q={keyword}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        if getattr(feed, "status", 200) == 429:
            time.sleep(5)
            feed = feedparser.parse(url)
            if getattr(feed, "status", 200) == 429:
                return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        items = []
        for entry in feed.entries[:20]:
            article_url = entry.get("link", "")
            if not article_url:
                continue
            published_struct = entry.get("published_parsed")
            if not published_struct:
                continue
            published_at = datetime(*published_struct[:6], tzinfo=timezone.utc)
            if published_at < cutoff:
                continue
            source_id = hashlib.sha256(article_url.encode()).hexdigest()
            items.append(NewsItem(
                source_type="google_news",
                source_id=source_id,
                title=entry.get("title", ""),
                url=article_url,
                published_at=published_at,
                keywords_matched=[keyword],
            ))
        return items


def load_news_keywords() -> dict[str, list[str]]:
    path = Path(__file__).parent.parent.parent / "config" / "news_keywords.json"
    return json.loads(path.read_text())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/discovery/test_news_scraper.py::test_google_news_adapter_parses_fixture -v`

Expected:
```
test_google_news_adapter_parses_fixture PASSED
1 passed
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt agents/discovery/news_scraper.py tests/discovery/fixtures/google_news_response.xml tests/discovery/test_news_scraper.py
git commit -m "feat: add NewsItem, NewsAdapter protocol, and GoogleNewsAdapter"
```

---

### Task 3: NewsAPIAdapter

**Files:**
- Modify: `agents/discovery/news_scraper.py` (add `NewsAPIAdapter` class)
- Create: `tests/discovery/fixtures/newsapi_response.json`
- Modify: `tests/discovery/test_news_scraper.py` (add NewsAPIAdapter tests)

- [ ] **Step 1: Write the failing test for NewsAPIAdapter**

Create `tests/discovery/fixtures/newsapi_response.json`:

```json
{
  "status": "ok",
  "totalResults": 2,
  "articles": [
    {
      "url": "https://newsapi.example.com/articles/insurance-claim-denied-1",
      "title": "Insurance claim denied after hurricane damage",
      "publishedAt": "2025-05-07T10:00:00Z"
    },
    {
      "url": "https://newsapi.example.com/articles/health-insurance-dispute-2",
      "title": "Health insurance coverage dispute resolved in court",
      "publishedAt": "2025-05-07T08:00:00Z"
    }
  ]
}
```

Add to `tests/discovery/test_news_scraper.py`:

```python
import json


def test_newsapi_adapter_parses_fixture():
    from agents.discovery.news_scraper import NewsAPIAdapter, NewsItem

    fixture = json.loads((FIXTURES_DIR / "newsapi_response.json").read_text())

    with patch("agents.discovery.news_scraper.requests.get") as mock_get:
        mock_get.return_value.json.return_value = fixture
        mock_get.return_value.raise_for_status.return_value = None
        items = NewsAPIAdapter(api_key="test_key").fetch("insurance claim denied", days=9999)

    assert len(items) == 2
    assert all(isinstance(i, NewsItem) for i in items)
    assert items[0].source_type == "newsapi"
    assert items[0].source_id == "https://newsapi.example.com/articles/insurance-claim-denied-1"
    assert items[0].title == "Insurance claim denied after hurricane damage"
    assert items[0].keywords_matched == ["insurance claim denied"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/discovery/test_news_scraper.py::test_newsapi_adapter_parses_fixture -v`

Expected: FAIL with `ImportError: cannot import name 'NewsAPIAdapter'`

- [ ] **Step 3: Add NewsAPIAdapter to news_scraper.py**

In `agents/discovery/news_scraper.py`, add after the `GoogleNewsAdapter` class:

```python
class NewsAPIAdapter:
    def __init__(self, api_key: str):
        self._api_key = api_key

    def fetch(self, keyword: str, days: int = 2) -> list[NewsItem]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        for attempt in range(2):
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={"q": keyword, "sortBy": "publishedAt", "language": "en", "pageSize": 20},
                headers={"X-Api-Key": self._api_key},
                timeout=10,
            )
            if resp.status_code == 429:
                if attempt == 0:
                    time.sleep(5)
                    continue
                return []
            resp.raise_for_status()
            items = []
            for article in resp.json().get("articles", [])[:20]:
                url = article.get("url", "")
                published_str = article.get("publishedAt", "")
                if not url or not published_str:
                    continue
                published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                if published_at < cutoff:
                    continue
                items.append(NewsItem(
                    source_type="newsapi",
                    source_id=url,
                    title=article.get("title", ""),
                    url=url,
                    published_at=published_at,
                    keywords_matched=[keyword],
                ))
            return items
        return []
```

- [ ] **Step 4: Run both adapter tests to verify they pass**

Run: `python3 -m pytest tests/discovery/test_news_scraper.py -v`

Expected:
```
test_google_news_adapter_parses_fixture PASSED
test_newsapi_adapter_parses_fixture PASSED
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/news_scraper.py tests/discovery/fixtures/newsapi_response.json tests/discovery/test_news_scraper.py
git commit -m "feat: add NewsAPIAdapter with 429 retry logic"
```

---

### Task 4: NewsScraper orchestrator and config/news_keywords.json

**Files:**
- Modify: `agents/discovery/news_scraper.py` (add `NewsScraper` class and `main()`)
- Create: `config/news_keywords.json`
- Modify: `tests/discovery/test_news_scraper.py` (add `NewsScraper` tests)

- [ ] **Step 1: Write the failing tests for NewsScraper**

Add to `tests/discovery/test_news_scraper.py`:

```python
from unittest.mock import patch, MagicMock, call


def test_news_scraper_raises_on_zero_articles():
    from agents.discovery.news_scraper import NewsScraper

    failing_adapter = MagicMock()
    failing_adapter.fetch.return_value = []

    with patch("agents.discovery.news_scraper.execute_with_retry") as mock_db:
        # First call: active niches; second call: known_pairs
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
    from datetime import timezone

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
            MagicMock(data=[]),                        # known_pairs: empty
            MagicMock(data=[{"id": "topic-new"}]),     # insert result
            MagicMock(data=[{}]),                      # app_settings upsert
        ]
        scraper = NewsScraper(
            supabase=MagicMock(),
            gate_client=MagicMock(),
            adapters=[mock_adapter],
            news_keywords={"legal": ["lawsuit settlement"]},
        )
        with patch.object(scraper, "_score_item", return_value=8.0):
            scraper.run()

    # Verify an insert was attempted
    insert_call = mock_db.call_args_list[2]
    insert_payload = insert_call[0][0].json()[0]  # first arg's json, first row
    assert insert_payload["source_type"] == "google_news"
    assert insert_payload["source_id"] == "abc123"
    assert insert_payload["niche_id"] == "niche-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/discovery/test_news_scraper.py::test_news_scraper_raises_on_zero_articles tests/discovery/test_news_scraper.py::test_news_scraper_inserts_high_scoring_topics -v`

Expected: FAIL with `ImportError: cannot import name 'NewsScraper'`

- [ ] **Step 3: Create config/news_keywords.json**

Create `config/news_keywords.json`:

```json
{
  "legal": ["lawsuit settlement", "class action", "supreme court ruling", "consumer rights"],
  "insurance": ["insurance claim denied", "health insurance", "coverage dispute"],
  "tax": ["IRS audit", "tax deadline", "tax refund"],
  "personal_finance": ["interest rates", "credit card debt", "student loan forgiveness"],
  "real_estate": ["housing market", "mortgage rates", "foreclosure"],
  "career": ["layoffs", "job market", "remote work policy"],
  "ai_tech": ["AI regulation", "ChatGPT", "AI job displacement"],
  "health": ["FDA approval", "drug recall", "medical study"]
}
```

- [ ] **Step 4: Add NewsScraper class and main() to news_scraper.py**

In `agents/discovery/news_scraper.py`, add these imports at the top (after existing imports):

```python
from supabase import Client
from agents.shared.gate_client import GateClient, GateNumber
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
```

Then add at the bottom of `news_scraper.py`:

```python
class NewsScraper:
    def __init__(
        self,
        supabase: Client,
        gate_client: GateClient,
        adapters: list,
        news_keywords: dict | None = None,
    ):
        self._sb = supabase
        self._gate = gate_client
        self._adapters = adapters
        self._keywords = news_keywords if news_keywords is not None else load_news_keywords()

    def run(self) -> None:
        active_niches = execute_with_retry(
            self._sb.table("niches").select("*").in_("status", ["testing", "promoted"])
        ).data

        known_pairs: set[tuple[str, str]] = {
            (row["source_type"], row["source_id"])
            for row in execute_with_retry(
                self._sb.table("topics")
                .select("source_type, source_id")
                .neq("source_type", "reddit")
            ).data
            if row.get("source_id")
        }

        total_fetched = 0

        for niche in active_niches:
            keywords = self._keywords.get(niche.get("category", ""), [])
            for keyword in keywords:
                for adapter in self._adapters:
                    try:
                        items = adapter.fetch(keyword, days=2)
                        total_fetched += len(items)
                        for item in items:
                            pair = (item.source_type, item.source_id)
                            if pair in known_pairs:
                                continue
                            claude_score = self._score_item(item)
                            if claude_score < 6:
                                print(f"[news] skipped (score {claude_score}): {item.title[:60]}")
                                continue
                            result = execute_with_retry(
                                self._sb.table("topics").insert({
                                    "niche_id": niche["id"],
                                    "source_type": item.source_type,
                                    "source_id": item.source_id,
                                    "title": item.title,
                                    "url": item.url,
                                    "body": "",
                                    "upvotes": 0,
                                    "claude_score": claude_score,
                                    "status": "pending",
                                    "gate2_state": "pending",
                                })
                            )
                            if not result.data:
                                continue
                            topic_id = result.data[0]["id"]
                            self._gate.advance_or_pause(
                                gate=GateNumber.TOPIC_SELECTION,
                                niche_id=niche["id"],
                                table="topics",
                                item_id=topic_id,
                                gate_column="gate2_state",
                                auto_state="approved",
                                review_state="awaiting_review",
                            )
                            known_pairs.add(pair)
                    except Exception as e:
                        print(f"[news] adapter error for '{keyword}': {e}")

        if total_fetched == 0:
            raise RuntimeError("news scraper: zero articles fetched — all adapters failed")

        execute_with_retry(
            self._sb.table("app_settings").upsert(
                [
                    {"key": "news_scraper_last_run_at", "value": datetime.now(timezone.utc).isoformat()},
                    {"key": "news_scraper_articles_fetched", "value": str(total_fetched)},
                ],
                on_conflict="key",
            )
        )
        print(f"[news] done. total articles fetched: {total_fetched}")

    def _score_item(self, item: NewsItem) -> float:
        from agents.shared.anthropic_client import complete
        prompt = (
            "Rate this news article for YouTube video potential. Score 1-10:\n"
            "- Clear story with conflict/resolution or surprising outcome\n"
            "- General audience appeal, not just insiders\n"
            "- Enough detail to sustain a 10-12 minute video\n"
            "- Relevant now but not purely breaking news\n\n"
            f"Title: {item.title}\n\n"
            "Return only the integer score."
        )
        try:
            score_str = complete(prompt, model="claude-haiku-4-5-20251001", max_tokens=10)
            return float(score_str.strip())
        except Exception:
            return 5.0


def main() -> None:
    from supabase import create_client
    from agents.shared.config_loader import get_env
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    gate = GateClient(sb)
    adapters: list = [GoogleNewsAdapter()]
    newsapi_key = os.getenv("NEWSAPI_KEY")
    if newsapi_key:
        adapters.append(NewsAPIAdapter(api_key=newsapi_key))
    scraper = NewsScraper(supabase=sb, gate_client=gate, adapters=adapters)
    scraper.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run all news_scraper tests to verify they pass**

Run: `python3 -m pytest tests/discovery/test_news_scraper.py -v`

Expected:
```
test_google_news_adapter_parses_fixture PASSED
test_newsapi_adapter_parses_fixture PASSED
test_news_scraper_raises_on_zero_articles PASSED
test_news_scraper_inserts_high_scoring_topics PASSED
4 passed
```

Note: `test_news_scraper_inserts_high_scoring_topics` patches `execute_with_retry` using `side_effect` with a list of mock return values. If the assertion on insert payload fails (the mock chain doesn't expose `.json()[0]` that way), simplify that assertion to:
```python
assert mock_db.call_count >= 3  # niches + known_pairs + insert
```

- [ ] **Step 6: Commit**

```bash
git add agents/discovery/news_scraper.py config/news_keywords.json tests/discovery/test_news_scraper.py
git commit -m "feat: add NewsScraper orchestrator and news_keywords.json"
```

---

### Task 5: GitHub Actions workflow for news_scraper

**Files:**
- Create: `.github/workflows/news_scraper.yml`

- [ ] **Step 1: Create the workflow file**

Read `.github/workflows/reddit_scraper.yml` for the exact secrets and step pattern, then create `.github/workflows/news_scraper.yml`:

```yaml
name: News Scraper

on:
  schedule:
    - cron: "0 6 * * *"   # daily at 06:00 UTC
  workflow_dispatch:

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run news scraper
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          NEWSAPI_KEY: ${{ secrets.NEWSAPI_KEY }}
        run: python3 -m agents.discovery.news_scraper
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/news_scraper.yml
git commit -m "feat: add daily GHA workflow for news_scraper"
```

**Note:** `NEWSAPI_KEY` is the one new secret that does not yet exist in the repo. Mat must add it to GitHub repo secrets before this workflow can run successfully. The `GoogleNewsAdapter` requires no API key and will run regardless.

---

### Task 6: NicheScorer news_velocity method and news_score field

**Files:**
- Modify: `agents/discovery/niche_scorer.py`
- Modify: `tests/discovery/test_niche_scorer.py`

- [ ] **Step 1: Write the failing tests for news_velocity**

Add to `tests/discovery/test_niche_scorer.py`:

```python
def test_news_velocity_returns_normalized_score():
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [MagicMock()] * 10  # 10 articles
    scorer = NicheScorer(
        youtube_client=MagicMock(),
        reddit_scraper=MagicMock(),
        news_adapters=[mock_adapter],
    )
    result = scorer.news_velocity("lawsuit settlement", days=10)
    assert result == 0.5  # 10 / 20 = 0.5


def test_news_velocity_clamps_at_one():
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [MagicMock()] * 25  # exceeds 20-article ceiling
    scorer = NicheScorer(
        youtube_client=MagicMock(),
        reddit_scraper=MagicMock(),
        news_adapters=[mock_adapter],
    )
    result = scorer.news_velocity("lawsuit settlement", days=10)
    assert result == 1.0


def test_news_velocity_returns_zero_on_adapter_failure():
    failing_adapter = MagicMock()
    failing_adapter.fetch.side_effect = Exception("connection error")
    scorer = NicheScorer(
        youtube_client=MagicMock(),
        reddit_scraper=MagicMock(),
        news_adapters=[failing_adapter],
    )
    result = scorer.news_velocity("lawsuit settlement", days=10)
    assert result == 0.0


def test_score_applies_news_signal():
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [MagicMock()] * 20  # max velocity = 1.0
    scorer = NicheScorer(
        youtube_client=MagicMock(),
        reddit_scraper=MagicMock(),
        news_adapters=[mock_adapter],
    )
    scorer._yt.get_rpm_estimate.return_value = (10.0, 10.0)
    scorer._reddit.fetch_top_posts.return_value = []
    scorer._yt.search.return_value = []

    with patch("agents.discovery.niche_scorer.TrendReq") as mock_trends:
        mock_df = MagicMock()
        mock_df.empty = True
        mock_trends.return_value.interest_over_time.return_value = mock_df
        result = scorer.score("lawsuit settlement", category="legal", subreddits=[])

    # With news_velocity=1.0, final_score should be base * 1.15
    assert result.news_score == 1.0
    assert result.final_score == round(result.final_score, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/discovery/test_niche_scorer.py::test_news_velocity_returns_normalized_score tests/discovery/test_niche_scorer.py::test_news_velocity_clamps_at_one tests/discovery/test_niche_scorer.py::test_news_velocity_returns_zero_on_adapter_failure -v`

Expected: FAIL with `TypeError: NicheScorer.__init__() got an unexpected keyword argument 'news_adapters'`

- [ ] **Step 3: Update niche_scorer.py**

Replace the full content of `agents/discovery/niche_scorer.py`:

```python
from dataclasses import dataclass, field
from typing import Any, List
from pytrends.request import TrendReq
from agents.discovery.youtube_client import YouTubeClient
from agents.discovery.reddit_scraper import RedditScraper


@dataclass
class NicheScoreResult:
    niche_name: str
    category: str
    final_score: float
    rpm_min: float
    rpm_max: float
    trend_score: float
    reddit_activity: float
    youtube_competition: float
    avg_rpm: float
    news_score: float = 0.0
    details: dict = field(default_factory=dict)


class NicheScorer:
    def __init__(
        self,
        youtube_client: YouTubeClient,
        reddit_scraper: RedditScraper,
        news_adapters: list | None = None,
    ):
        self._yt = youtube_client
        self._reddit = reddit_scraper
        self._news_adapters = news_adapters or []

    def score(
        self,
        niche_name: str,
        category: str,
        subreddits: List[str],
    ) -> NicheScoreResult:
        rpm_min, rpm_max = self._yt.get_rpm_estimate(category)
        avg_rpm = (rpm_min + rpm_max) / 2

        trend_score = self._get_trend_score(niche_name)
        reddit_activity = self._get_reddit_activity(subreddits)
        yt_videos = self._yt.search(niche_name, max_results=10)
        competition_score = self._compute_competition(yt_videos)

        if competition_score > 0:
            base_score = (avg_rpm * trend_score * reddit_activity) / competition_score
        else:
            base_score = avg_rpm * trend_score * reddit_activity

        news_score = self.news_velocity(niche_name) if self._news_adapters else 0.0
        final_score = base_score * (1 + 0.15 * news_score)

        return NicheScoreResult(
            niche_name=niche_name,
            category=category,
            final_score=round(final_score, 2),
            rpm_min=rpm_min,
            rpm_max=rpm_max,
            trend_score=trend_score,
            reddit_activity=reddit_activity,
            youtube_competition=competition_score,
            avg_rpm=avg_rpm,
            news_score=news_score,
            details={
                "yt_video_count": len(yt_videos),
                "yt_source": yt_videos[0].source if yt_videos else "rpm_proxy",
            },
        )

    def news_velocity(self, keyword: str, days: int = 10) -> float:
        total = 0
        for adapter in self._news_adapters:
            try:
                items = adapter.fetch(keyword, days=days)
                total += len(items)
            except Exception as e:
                print(f"[scorer] news_velocity adapter failed for '{keyword}': {e}")
        return min(total / 20, 1.0)

    def _get_trend_score(self, keyword: str) -> float:
        try:
            pytrends = TrendReq(hl="en-US", tz=360)
            pytrends.build_payload([keyword], timeframe="today 12-m")
            df = pytrends.interest_over_time()
            if df.empty:
                return 1.0
            series = df[keyword]
            recent = float(series.iloc[-4:].mean())
            overall = float(series.mean())
            return round(recent / overall, 2) if overall > 0 else 1.0
        except Exception:
            return 1.0

    def _get_reddit_activity(self, subreddits: List[str]) -> float:
        total_score = 0
        count = 0
        for sub in subreddits[:3]:
            try:
                posts = self._reddit.fetch_top_posts(sub, min_score=100, min_body_length=0, limit=10)
                if posts:
                    total_score += sum(p.score for p in posts) / len(posts)
                    count += 1
            except Exception:
                pass
        if count == 0:
            return 1.0
        avg = total_score / count
        return round(min(avg / 1000, 10.0), 2)

    def _compute_competition(self, videos: List[Any]) -> float:
        if not videos:
            return 1.0
        avg_views = sum(v.view_count for v in videos) / len(videos)
        return round(min(avg_views / 100000, 10.0), 2)
```

- [ ] **Step 4: Run all niche_scorer tests to verify they pass**

Run: `python3 -m pytest tests/discovery/test_niche_scorer.py -v`

Expected:
```
test_score_returns_result_with_all_fields PASSED
test_score_handles_no_youtube_results PASSED
test_score_returns_one_when_trend_mean_is_zero PASSED
test_news_velocity_returns_normalized_score PASSED
test_news_velocity_clamps_at_one PASSED
test_news_velocity_returns_zero_on_adapter_failure PASSED
test_score_applies_news_signal PASSED
7 passed
```

- [ ] **Step 5: Commit**

```bash
git add agents/discovery/niche_scorer.py tests/discovery/test_niche_scorer.py
git commit -m "feat: add news_velocity() to NicheScorer and news_score to NicheScoreResult"
```

---

### Task 7: NicheScout news discovery pass

**Files:**
- Modify: `agents/discovery/niche_scout.py`
- Modify: `tests/discovery/test_niche_scout.py`

- [ ] **Step 1: Write the failing test for the news discovery pass**

Add to `tests/discovery/test_niche_scout.py`:

```python
def test_run_includes_news_discovered_candidates():
    from agents.discovery.niche_scorer import NicheScoreResult

    mock_sb = MagicMock()
    mock_scorer = MagicMock()
    mock_gate = MagicMock()

    # Adapter returns 6 articles for any keyword (above 5-article threshold)
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = [MagicMock()] * 6

    mock_scorer.score.return_value = NicheScoreResult(
        niche_name="test", category="legal", final_score=42.0,
        rpm_min=10.0, rpm_max=20.0, trend_score=1.2,
        reddit_activity=3.0, youtube_competition=2.0, avg_rpm=15.0,
    )
    mock_sb.table.return_value.select.return_value.execute.return_value.data = []
    mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]

    scout = NicheScout(
        supabase=mock_sb,
        scorer=mock_scorer,
        gate_client=mock_gate,
        news_adapters=[mock_adapter],
        news_keywords={"legal": ["lawsuit settlement"]},
    )
    scout.run()

    # scorer.score() called for CATEGORY_QUERIES (8) + news candidates (1)
    assert mock_scorer.score.call_count == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/discovery/test_niche_scout.py::test_run_includes_news_discovered_candidates -v`

Expected: FAIL with `TypeError: NicheScout.__init__() got an unexpected keyword argument 'news_adapters'`

- [ ] **Step 3: Update niche_scout.py**

Replace the full content of `agents/discovery/niche_scout.py`:

```python
import os
from typing import List
from supabase import Client, create_client
from agents.discovery.niche_scorer import NicheScorer, NicheScoreResult
from agents.discovery.youtube_client import YouTubeClient
from agents.discovery.reddit_scraper import RedditScraper
from agents.discovery.news_scraper import GoogleNewsAdapter, NewsAPIAdapter, load_news_keywords
from agents.shared.gate_client import GateClient
from agents.shared.config_loader import get_env, get_subreddits
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1


CATEGORY_QUERIES = {
    "legal": "know your legal rights lawsuit",
    "insurance": "insurance claim denied tips",
    "tax": "tax mistakes to avoid IRS",
    "personal_finance": "personal finance money mistakes",
    "real_estate": "real estate buying mistakes",
    "career": "salary negotiation tips",
    "ai_tech": "AI tools that changed my workflow",
    "health": "medical symptoms you should not ignore",
}


class NicheScout:
    def __init__(
        self,
        supabase: Client,
        scorer: NicheScorer,
        gate_client: GateClient,
        news_adapters: list | None = None,
        news_keywords: dict | None = None,
    ):
        self._sb = supabase
        self._scorer = scorer
        self._gate = gate_client
        self._news_adapters = news_adapters or []
        self._news_keywords = news_keywords  # None means load from file in run()

    def run(self) -> None:
        subreddits_map = get_subreddits()
        existing = {
            row["name"]
            for row in execute_with_retry(self._sb.table("niches").select("name")).data
        }

        results: list[NicheScoreResult] = []

        # Pass 1: score standard CATEGORY_QUERIES candidates
        for category, query in CATEGORY_QUERIES.items():
            subs = subreddits_map.get(category, [])
            try:
                result = self._scorer.score(query, category=category, subreddits=subs)
                results.append(result)
                print(f"[scout] {category}: score={result.final_score}")
            except Exception as e:
                print(f"[scout] failed to score {category}: {e}")

        # Pass 2: news-velocity-based candidate discovery
        if self._news_adapters:
            keywords_map = self._news_keywords if self._news_keywords is not None else load_news_keywords()
            for category, keywords in keywords_map.items():
                for keyword in keywords:
                    article_count = sum(
                        len(adapter.fetch(keyword, days=2))
                        for adapter in self._news_adapters
                    )
                    if article_count < 5:
                        continue
                    if keyword in existing:
                        continue
                    subs = subreddits_map.get(category, [])
                    try:
                        result = self._scorer.score(keyword, category=category, subreddits=subs)
                        results.append(result)
                        print(f"[scout] news candidate '{keyword}': score={result.final_score}")
                    except Exception as e:
                        print(f"[scout] failed to score news candidate '{keyword}': {e}")

        results.sort(key=lambda r: r.final_score, reverse=True)

        seen_names = set(existing)
        inserted = 0
        for r in results[:5]:
            if r.niche_name in seen_names:
                continue
            execute_with_retry(self._sb.table("niches").upsert(
                {
                    "name": r.niche_name,
                    "category": r.category,
                    "status": "candidate",
                    "score": r.final_score,
                    "rpm_min": r.rpm_min,
                    "rpm_max": r.rpm_max,
                    "subreddits": subreddits_map.get(r.category, []),
                    "niche_source": "scout",
                    "gate1_state": "awaiting_review",
                },
                on_conflict="name",
            ))
            seen_names.add(r.niche_name)
            inserted += 1
        print(f"[scout] done. top candidates queued: {inserted}")


def main():
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    yt = YouTubeClient(rapidapi_key=os.getenv("RAPIDAPI_KEY", ""))
    reddit = RedditScraper()
    news_adapters: list = [GoogleNewsAdapter()]
    newsapi_key = os.getenv("NEWSAPI_KEY")
    if newsapi_key:
        news_adapters.append(NewsAPIAdapter(api_key=newsapi_key))
    scorer = NicheScorer(youtube_client=yt, reddit_scraper=reddit, news_adapters=news_adapters)
    gate = GateClient(sb)
    scout = NicheScout(supabase=sb, scorer=scorer, gate_client=gate, news_adapters=news_adapters)
    scout.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all niche_scout tests to verify they pass**

Run: `python3 -m pytest tests/discovery/test_niche_scout.py -v`

Expected:
```
test_run_scores_all_categories PASSED
test_run_upserts_top_candidates PASSED
test_run_includes_news_discovered_candidates PASSED
3 passed
```

- [ ] **Step 5: Run the full test suite to verify no regressions**

Run: `python3 -m pytest tests/ -v`

Expected: All tests pass (0 failures).

- [ ] **Step 6: Commit**

```bash
git add agents/discovery/niche_scout.py tests/discovery/test_niche_scout.py
git commit -m "feat: add news discovery pass to NicheScout"
```

---

## Self-Review Checklist

Spec coverage check:
- [x] Migration 007 with source_type/source_id, backfill, constraint swap — Task 1
- [x] reddit_post_id retained (not dropped), made nullable — Task 1
- [x] NewsItem Pydantic model (ValidationError on bad API response) — Task 2
- [x] NewsAdapter Protocol — Task 2
- [x] GoogleNewsAdapter (feedparser, SHA-256 source_id, ≤20 results) — Task 2
- [x] NewsAPIAdapter (requests, source_id = URL, 429 retry) — Task 3
- [x] NewsScraper orchestrator (per-niche iteration, gate advance, dedup by source_type+source_id) — Task 4
- [x] config/news_keywords.json (all 8 categories) — Task 4
- [x] Zero-articles RuntimeError — Task 4
- [x] app_settings last_run_at + articles_fetched write — Task 4
- [x] GHA workflow (daily 06:00 UTC, NEWSAPI_KEY secret noted) — Task 5
- [x] NicheScorer.news_velocity() (10-day window, 0–1.0 clamped, fail→0.0) — Task 6
- [x] news_score field on NicheScoreResult — Task 6
- [x] Score formula: base * (1 + 0.15 * news_score) — Task 6
- [x] NicheScout pass 2: ≥5 articles/48h → candidate — Task 7
- [x] NicheScout dedup against existing niches — Task 7
- [x] Fixture-based tests for both adapters — Tasks 2, 3
- [x] NewsScraper zero-articles test — Task 4
- [x] news_velocity normalization and clamp tests — Task 6
