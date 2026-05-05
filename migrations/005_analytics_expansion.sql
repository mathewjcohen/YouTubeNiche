-- migrations/005_analytics_expansion.sql

-- Add updated_at to scripts so voiceover agent can detect stuck-processing rows
alter table scripts add column if not exists updated_at timestamptz default now();

create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

drop trigger if exists scripts_updated_at on scripts;
create trigger scripts_updated_at
  before update on scripts
  for each row execute function set_updated_at();

-- -----------------------------------------------------------------------
-- Expand niche_analytics with granular metrics
-- -----------------------------------------------------------------------
alter table niche_analytics
  add column if not exists avg_view_duration_sec  numeric,
  add column if not exists impressions             integer default 0,
  add column if not exists long_views              integer default 0,
  add column if not exists long_avg_view_duration_sec numeric,
  add column if not exists long_avg_watch_pct      numeric,
  add column if not exists short_views             integer default 0,
  add column if not exists short_avg_view_duration_sec numeric,
  add column if not exists short_avg_watch_pct     numeric,
  add column if not exists subscribers_gained      integer default 0,
  add column if not exists estimated_minutes_watched integer default 0,
  add column if not exists likes                   integer default 0,
  add column if not exists videos_published        integer default 0,
  add column if not exists shorts_published        integer default 0;

-- -----------------------------------------------------------------------
-- Per-video analytics — one row per video per poll
-- -----------------------------------------------------------------------
create table if not exists video_analytics (
  id                    uuid primary key default gen_random_uuid(),
  niche_id              uuid not null references niches(id),
  youtube_video_id      text not null,
  video_type            text not null check (video_type in ('long', 'short')),
  polled_at             timestamptz default now(),
  views                 integer default 0,
  avg_view_duration_sec numeric,
  avg_view_pct          numeric,
  estimated_minutes_watched numeric,
  likes                 integer default 0
);

create index if not exists idx_video_analytics_niche  on video_analytics(niche_id, polled_at desc);
create index if not exists idx_video_analytics_video  on video_analytics(youtube_video_id, polled_at desc);
