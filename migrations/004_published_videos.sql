-- migrations/004_published_videos.sql

create table if not exists published_videos (
  id uuid primary key default gen_random_uuid(),
  niche_id uuid not null references niches(id),
  script_id uuid not null references scripts(id),
  youtube_video_id text not null,
  video_type text not null check (video_type in ('long', 'short')),
  uploaded_at timestamptz default now()
);

create index if not exists idx_published_videos_niche on published_videos(niche_id);
create index if not exists idx_published_videos_script on published_videos(script_id, video_type);
