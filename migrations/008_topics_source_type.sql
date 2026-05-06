-- Add source_type and source_id to topics
ALTER TABLE topics
  ADD COLUMN source_type text NOT NULL DEFAULT 'reddit',
  ADD COLUMN source_id   text;

-- Backfill source_id from reddit_post_id
UPDATE topics
   SET source_id = reddit_post_id
 WHERE reddit_post_id IS NOT NULL;

-- Drop old unique constraint (was: UNIQUE(reddit_post_id))
ALTER TABLE topics
  DROP CONSTRAINT IF EXISTS topics_reddit_post_id_key;

-- Make reddit_post_id nullable (deprecated, retained for read compat)
ALTER TABLE topics
  ALTER COLUMN reddit_post_id DROP NOT NULL;

-- New composite unique constraint
ALTER TABLE topics
  ADD CONSTRAINT topics_source_type_source_id_key UNIQUE (source_type, source_id);
