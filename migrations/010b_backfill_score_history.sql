-- Backfill niche_score_history with scores already stored on niches rows.
-- Run once after 010_niche_score_history.sql has been applied.
INSERT INTO niche_score_history (niche_name, category, final_score, recorded_at)
SELECT
  name,
  category,
  score,
  now()
FROM niches
WHERE score IS NOT NULL;
