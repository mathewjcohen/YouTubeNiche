import os
from typing import List
from supabase import Client, create_client
from agents.discovery.niche_scorer import NicheScorer, NicheScoreResult
from agents.discovery.youtube_client import YouTubeClient
from agents.discovery.reddit_scraper import RedditScraper
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
    def __init__(self, supabase: Client, scorer: NicheScorer, gate_client: GateClient):
        self._sb = supabase
        self._scorer = scorer
        self._gate = gate_client

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

        results.sort(key=lambda r: r.final_score, reverse=True)
        print(f"[scout] existing niches in DB: {len(existing)} — {list(existing)[:5]}")
        inserted = 0
        for r in results[:5]:
            if r.niche_name in existing:
                print(f"[scout] skip duplicate: {r.niche_name}")
                continue
            result = execute_with_retry(self._sb.table("niches").upsert(
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
            print(f"[scout] upsert {r.niche_name}: data={result.data} count={result.count}")
            inserted += 1
        print(f"[scout] done. inserted={inserted} of top {min(5, len(results))}")


def main():
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    yt = YouTubeClient(rapidapi_key=os.getenv("RAPIDAPI_KEY", ""))
    reddit = RedditScraper()
    scorer = NicheScorer(youtube_client=yt, reddit_scraper=reddit)
    gate = GateClient(sb)
    scout = NicheScout(supabase=sb, scorer=scorer, gate_client=gate)
    scout.run()


if __name__ == "__main__":
    main()
