import hashlib
import os
import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Protocol

import feedparser
import requests
from pydantic import BaseModel


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


def load_news_keywords() -> dict:
    path = Path(__file__).parent.parent.parent / "config" / "news_keywords.json"
    return json.loads(path.read_text())
