import os
import json
from typing import Any, Dict, List, Optional
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
        news_adapters: Optional[List[Any]] = None,
        news_keywords: Optional[Dict[str, List[str]]] = None,
    ):
        self._sb = supabase
        self._scorer = scorer
        self._gate = gate_client
        self._news_adapters = news_adapters or []
        self._news_keywords = news_keywords or {}

    def run(self) -> None:
        subreddits_map = get_subreddits()
        existing = {
            row["name"]
            for row in execute_with_retry(self._sb.table("niches").select("name")).data
        }

        results: List[NicheScoreResult] = []
        for category, query in CATEGORY_QUERIES.items():
            subs = subreddits_map.get(category, [])
            try:
                result = self._scorer.score(query, category=category, subreddits=subs)
                results.append(result)
                print(f"[scout] {category}: score={result.final_score}")
            except Exception as e:
                print(f"[scout] failed to score {category}: {e}")

        # Pass 2: news-velocity niche discovery
        if self._news_adapters and self._news_keywords:
            seen_candidates = {r.niche_name for r in results}
            for category, keywords in self._news_keywords.items():
                for keyword in keywords:
                    total = 0
                    for adapter in self._news_adapters:
                        try:
                            items = adapter.fetch(keyword, days=2)
                            total += len(items)
                        except Exception as e:
                            print(f"[scout] news adapter failed for '{keyword}': {e}")
                    if total >= 5 and keyword not in existing and keyword not in seen_candidates:
                        try:
                            result = self._scorer.score(keyword, category=category, subreddits=[])
                            results.append(result)
                            seen_candidates.add(keyword)
                            print(f"[scout] news candidate '{keyword}': score={result.final_score}")
                        except Exception as e:
                            print(f"[scout] failed to score news candidate '{keyword}': {e}")

        results.sort(key=lambda r: r.final_score, reverse=True)
        inserted = 0
        for r in results[:5]:
            if r.niche_name in existing:
                continue
            execute_with_retry(self._sb.table("niches").upsert(
                {
                    "name": r.niche_name,
                    "category": r.category,
                    "status": "candidate",
                    "score": r.final_score,
                    "rpm_min": r.rpm_min,
                    "rpm_max": r.rpm_max,
                    "score_details": {
                        "rpm": round(r.avg_rpm, 2),
                        "trend": r.trend_score,
                        "reddit": r.reddit_activity,
                        "competition": r.youtube_competition,
                        "news": r.news_score,
                    },
                    "subreddits": subreddits_map.get(r.category, []),
                    "niche_source": "scout",
                    "gate1_state": "awaiting_review",
                },
                on_conflict="name",
            ))
            inserted += 1
        print(f"[scout] done. top candidates queued: {inserted}")


def main():
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    yt = YouTubeClient(rapidapi_key=os.getenv("RAPIDAPI_KEY", ""))
    reddit = RedditScraper()

    news_adapters: List[Any] = [GoogleNewsAdapter()]
    newsapi_key = os.getenv("NEWSAPI_KEY")
    if newsapi_key:
        news_adapters.append(NewsAPIAdapter(api_key=newsapi_key))
    news_kws = load_news_keywords()

    scorer = NicheScorer(youtube_client=yt, reddit_scraper=reddit, news_adapters=news_adapters)
    gate = GateClient(sb)
    scout = NicheScout(
        supabase=sb,
        scorer=scorer,
        gate_client=gate,
        news_adapters=news_adapters,
        news_keywords=news_kws,
    )
    scout.run()


if __name__ == "__main__":
    main()
