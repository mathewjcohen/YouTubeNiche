-- migrations/012_published_videos_script_nullable.sql
-- Allow script_id to be NULL so the analytics poller can insert rows for
-- videos discovered on the channel that were uploaded outside the pipeline.

alter table published_videos
  alter column script_id drop not null;
