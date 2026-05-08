-- migrations/014_published_videos_thumbnail_retry.sql
-- When a YouTube thumbnail set fails (e.g. quota exhaustion), preserve the
-- source URL here so the retry runner can attempt the set after quota resets.
-- Cleared to NULL once the thumbnail is successfully applied.

alter table published_videos
  add column if not exists thumbnail_path text;
