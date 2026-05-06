---
title: News Sources & Niche Scout Extension
date: 2026-05-06
status: approved
tags: [spec, youtubeniche, news, niche-scout, topics]
---

# News Sources & Niche Scout Extension

## Goal

Add pluggable news source adapters to feed timely topics into the pipeline, and extend the Niche Scout to discover new niches from trending news and use news volume as a scoring signal for existing candidates.

## Architecture

Two parallel additions that share a common `NewsAdapter` protocol and `config/news_keywords.json`:

1. **News Scraper** — new agent (`agents/discovery/news_scraper.py`) that queries pluggable `NewsAdapter` implementations, deduplicates against the `topics` table, and writes qualifying articles as topics.
2. **Niche Scout Extension** — extends `agents/discovery/niche_scout.py` to (a) treat high-velocity news clusters as niche candidates and (b) add a news velocity score into `NicheScorer`.

---

## Schema Changes

### Migration: `migrations/007_topics_source_type.sql`

- Add `source_type text not null default 'reddit'` to `topics`
- Add `source_id text` to `topics` (replaces `reddit_post_id` semantically)
- Drop existing `unique(reddit_post_id)` constraint
- Add `unique(source_type, source_id)` constraint
- Backfill: `UPDATE topics SET source_type = 'reddit', source_id = reddit_post_id WHERE reddit_post_id IS NOT NULL`
- `reddit_post_id` column retained but deprecated — no new writes after migration

---

## Files

### New
| Path | Responsibility |
|---|---|
| `agents/discovery/news_scraper.py` | `NewsItem` Pydantic model, `NewsAdapter` Protocol, `GoogleNewsAdapter`, `NewsAPIAdapter`, `NewsScraper` orchestrator |
| `config/news_keywords.json` | Keyword lists per category (mirrors `config/subreddits.json` structure) |
| `.github/workflows/news_scraper.yml` | Daily cron GHA workflow |

### Modified
| Path | Change |
|---|---|
| `agents/discovery/niche_scout.py` | News-based candidate discovery pass + `news_velocity` signal |

---

## Component Design

### `NewsItem` and `NewsAdapter`

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Protocol

class NewsItem(BaseModel):
    source_type: str        # "google_news" | "newsapi"
    source_id: str          # stable unique identifier (see per-adapter notes)
    title: str
    url: str
    published_at: datetime
    keywords_matched: list[str]

class NewsAdapter(Protocol):
    def fetch(self, keyword: str, days: int = 2) -> list[NewsItem]: ...
```

Pydantic validation on `NewsItem` is the primary schema-change defence. Any upstream API response that no longer maps cleanly to the model raises a `ValidationError` immediately — there is no silent empty return.

### `GoogleNewsAdapter`

- Endpoint: `https://news.google.com/rss/search?q={keyword}&hl=en-US&gl=US&ceid=US:en`
- No API key required
- Parse: XML via `feedparser`
- `source_type`: `"google_news"`
- `source_id`: SHA-256 hash of the article URL (URLs are stable per article)
- Returns up to 20 results per keyword

### `NewsAPIAdapter`

- Endpoint: `https://newsapi.org/v2/everything?q={keyword}&sortBy=publishedAt&language=en`
- Requires `NEWSAPI_KEY` env var (free developer tier: 100 req/day)
- Parse: JSON
- `source_type`: `"newsapi"`
- `source_id`: article `url` field (unique per article in NewsAPI)
- Returns up to 20 results per keyword

### `NewsScraper` orchestrator

Follows the same pattern as `reddit_scraper.py`: fetches all active niches itself, iterates per-niche, inserts topics with `niche_id` set.

1. Fetch all active niches (`status in ('testing', 'promoted')`) from Supabase
2. Load `config/news_keywords.json`
3. For each niche: look up `news_keywords[niche["category"]]` for keywords (same fallback pattern as reddit scraper's `subreddits_map`)
4. For each keyword: call all adapters in sequence
5. Deduplicate by `(source_type, source_id)` against existing `topics` rows (same article claimed by first niche to process it, matching reddit deduplication behaviour)
6. Score new items via Claude (reuse existing scoring prompt from `reddit_scraper.py`)
7. Insert items scoring ≥ 6 to `topics` with `niche_id`, `source_type`, `source_id`
8. After all niches processed:
   - If `total_articles_fetched == 0`: raise `RuntimeError("news scraper: zero articles fetched — all adapters failed")` → fails GHA job → email alert
   - Write `news_scraper_last_run_at` (ISO timestamp) and `news_scraper_articles_fetched` (int as string) to `app_settings` table

### `config/news_keywords.json`

Structure mirrors `config/subreddits.json` — same category keys, keyword phrases as values:

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

### GHA Workflow: `news_scraper.yml`

- Schedule: daily at 06:00 UTC (before the pipeline's hourly runs, so fresh topics are available)
- Manual trigger: `workflow_dispatch`
- Single job: install deps, run `python3 -m agents.discovery.news_scraper`
- Uses existing repo secrets (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`) plus `NEWSAPI_KEY` — **this is a new secret that must be added to the repo before the workflow can run**

---

## Niche Scout Extension

### New niche discovery pass

After scoring existing `CATEGORY_QUERIES` candidates, the scout runs a second pass:

1. Call all `NewsAdapter`s for each keyword in `config/news_keywords.json`
2. Any keyword that produced **≥ 5 articles in the last 48 hours** becomes a niche candidate (keyword used as candidate name)
3. Each candidate passed through existing `NicheScorer` (trends + reddit + youtube signals + new news velocity signal)
4. Deduplicate against existing niches and existing candidates before "insert top 5" step

### News velocity signal

`NicheScorer` gains a `news_velocity(keyword: str) -> float` method:

- Queries all adapters for the keyword over the last **10 days** (window chosen to outlast pipeline lag of 3-5 days from topic to upload)
- Normalises article count: 0 articles → 0.0, 20+ articles → 1.0 (linear, clamped)
- Weight in composite score: **0.15** (same weight as existing reddit signal)
- If all adapter calls fail: method returns 0.0, candidate is scored without news signal (not skipped)

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Single adapter raises | Logged, run continues with remaining adapters |
| HTTP 429 rate limit | Single retry after 5s, then skip keyword for that adapter |
| All adapters return zero articles | `RuntimeError` raised → GHA job fails → email notification |
| Pydantic `ValidationError` on API response | Logged with full response excerpt, item skipped |
| News velocity call fails in NicheScorer | Returns 0.0, scoring continues without news signal |

---

## Testing

- Each adapter tested with a saved fixture (JSON for NewsAPI, XML for Google News) verifying parse → valid `NewsItem`
- Pydantic model enforces that fixture tests also validate model shape; if production response format drifts, the adapter's parse logic raises on real runs before tests can hide it
- `NicheScorer.news_velocity()` tested with a mock adapter returning a known article count → assert expected normalised float
- `NewsScraper` zero-articles path tested: mock all adapters returning empty → assert `RuntimeError` raised
- No live HTTP calls in test suite

---

## Open Questions / Non-Goals

- Dashboard widget for `news_scraper_last_run_at` / `news_scraper_articles_fetched`: out of scope; data will be in `app_settings` and readable via Supabase dashboard in the meantime.
