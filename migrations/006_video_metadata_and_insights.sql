-- migrations/006_video_metadata_and_insights.sql

-- -----------------------------------------------------------------------
-- published_videos: title + duration for video table display
-- -----------------------------------------------------------------------
alter table published_videos
  add column if not exists title       text,
  add column if not exists duration_sec integer;

-- Backfill title from scripts (ground truth is YouTube API; this seeds it)
update published_videos pv
set title = s.youtube_title
from scripts s
where pv.script_id = s.id
  and pv.title is null
  and s.youtube_title is not null;

-- -----------------------------------------------------------------------
-- video_analytics: audience retention curve per video per poll
-- -----------------------------------------------------------------------
alter table video_analytics
  add column if not exists audience_retention_json jsonb;
  -- stored as {"0.01": 0.95, "0.10": 0.87, ..., "1.00": 0.12}
  -- keys = elapsedVideoTimeRatio (0–1), values = audienceWatchRatio (0–1)

-- -----------------------------------------------------------------------
-- niche_analytics: dimension breakdowns
-- -----------------------------------------------------------------------
alter table niche_analytics
  add column if not exists traffic_sources   jsonb,
  -- {"YT_SEARCH": 0.40, "BROWSE_FEATURES": 0.30, "EXT_URL": 0.10, ...}
  add column if not exists top_countries     jsonb,
  -- {"US": 0.45, "CA": 0.12, "GB": 0.08, ...}
  add column if not exists device_types      jsonb,
  -- {"MOBILE": 0.62, "DESKTOP": 0.28, "TABLET": 0.05, "TV": 0.05}
  add column if not exists subscriber_ratio  numeric;
  -- fraction of views from subscribed users (0–1)

-- -----------------------------------------------------------------------
-- insights: pattern analysis output (stats + LLM summary)
-- -----------------------------------------------------------------------
create table if not exists insights (
  id             uuid primary key default gen_random_uuid(),
  generated_at   timestamptz default now(),
  period_days    integer not null default 30,
  stats_json     jsonb not null,
  summary_text   text not null
);

create index if not exists idx_insights_generated_at on insights(generated_at desc);
