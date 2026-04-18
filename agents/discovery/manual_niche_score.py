"""
Entrypoint for GitHub Actions workflow_dispatch.
Usage: python -m agents.discovery.manual_niche_score --niche "personal injury law" --category legal
"""
import argparse
import os
from supabase import create_client
from agents.discovery.niche_scorer import NicheScorer
from agents.discovery.youtube_client import YouTubeClient
from agents.discovery.reddit_scraper import RedditScraper
from agents.shared.config_loader import get_env, get_subreddits
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", required=True, help="Niche name or query")
    parser.add_argument("--category", required=True, help="Category key from rpm table")
    args = parser.parse_args()

    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    yt = YouTubeClient(rapidapi_key=os.getenv("RAPIDAPI_KEY", ""))
    reddit = RedditScraper()
    scorer = NicheScorer(youtube_client=yt, reddit_scraper=reddit)
    subreddits_map = get_subreddits()
    subs = subreddits_map.get(args.category, [])

    result = scorer.score(args.niche, category=args.category, subreddits=subs)

    print(f"[manual-score] niche={result.niche_name} score={result.final_score}")
    print(f"  RPM: ${result.rpm_min}–${result.rpm_max}")
    print(f"  trend={result.trend_score} reddit={result.reddit_activity} competition={result.youtube_competition}")

    execute_with_retry(sb.table("niches").upsert(
        {
            "name": result.niche_name,
            "category": result.category,
            "status": "candidate",
            "score": result.final_score,
            "rpm_min": result.rpm_min,
            "rpm_max": result.rpm_max,
            "subreddits": subs,
            "niche_source": "manual",
            "gate1_state": "awaiting_review",
        },
        on_conflict="name",
    ))
    print("[manual-score] written to Supabase. Check dashboard Niches page.")


if __name__ == "__main__":
    main()
