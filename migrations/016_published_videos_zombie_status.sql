-- migrations/016_published_videos_zombie_status.sql
-- Add 'zombie' as a valid status for published_videos.
-- Zombies are videos >30 days old with zero lifetime views.

alter table published_videos
  drop constraint if exists published_videos_status_check;

alter table published_videos
  add constraint published_videos_status_check
    check (status in ('live', 'removed', 'private', 'zombie'));
