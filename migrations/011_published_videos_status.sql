-- migrations/011_published_videos_status.sql
-- Track YouTube-side status for published videos (live / removed / private).

alter table published_videos
  add column if not exists status     text not null default 'live'
    check (status in ('live', 'removed', 'private')),
  add column if not exists removed_at timestamptz;

create index if not exists idx_published_videos_status on published_videos(status);
