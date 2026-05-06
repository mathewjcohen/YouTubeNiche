-- Add 'uploading' to the videos status check constraint.
-- The uploader sets status='uploading' as an atomic claim to prevent
-- concurrent pipeline runs from double-uploading the same video.
-- The original constraint omitted this transient state.

ALTER TABLE videos DROP CONSTRAINT videos_status_check;
ALTER TABLE videos ADD CONSTRAINT videos_status_check
  CHECK (status IN ('pending','processing','awaiting_review','approved','rejected','uploaded','uploading'));
