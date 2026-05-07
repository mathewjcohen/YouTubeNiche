import hashlib
import os
import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Protocol
from urllib.parse import quote_plus

import feedparser
import requests
from pydantic import BaseModel

from supabase import Client
from agents.shared.gate_client import GateClient, GateNumber
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.shared.article_fetcher import fetch_article_body


class NewsItem(BaseModel):
    source_type: str
    source_id: str
    title: str
    url: str
    published_at: datetime
    keywords_matched: List[str]


class NewsAdapter(Protocol):
    def fetch(self, keyword: str, days: int = 2) -> List[NewsItem]: ...


class GoogleNewsAdapter:
    def fetch(self, keyword: str, days: int = 2) -> List[NewsItem]:
        url = f"https://news.google.com/rss/search?q={quote_plus(keyword)}&hl=en-US&gl=US&ceid=US:en"
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


class NewsAPIAdapter:
    def __init__(self, api_key: str):
        self._api_key = api_key

    def fetch(self, keyword: str, days: int = 2) -> List[NewsItem]:
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


def load_news_keywords() -> dict:
    path = Path(__file__).parent.parent.parent / "config" / "news_keywords.json"
    return json.loads(path.read_text())


class NewsScraper:
    def __init__(
        self,
        supabase: Client,
        gate_client: GateClient,
        adapters: List,
        news_keywords: Optional[dict] = None,
    ):
        self._sb = supabase
        self._gate = gate_client
        self._adapters = adapters
        self._keywords = news_keywords if news_keywords is not None else load_news_keywords()

    def run(self) -> None:
        active_niches = execute_with_retry(
            self._sb.table("niches").select("*").in_("status", ["testing", "promoted"])
        ).data

        known_pairs: set = {
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
                            body = fetch_article_body(item.url)
                            print(f"[news] fetched body ({len(body)} chars): {item.title[:50]}")
                            result = execute_with_retry(
                                self._sb.table("topics").insert({
                                    "niche_id": niche["id"],
                                    "source_type": item.source_type,
                                    "source_id": item.source_id,
                                    "title": item.title,
                                    "url": item.url,
                                    "body": body,
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
    adapters: List = [GoogleNewsAdapter()]
    newsapi_key = os.getenv("NEWSAPI_KEY")
    if newsapi_key:
        adapters.append(NewsAPIAdapter(api_key=newsapi_key))
    scraper = NewsScraper(supabase=sb, gate_client=gate, adapters=adapters)
    scraper.run()


if __name__ == "__main__":
    main()
