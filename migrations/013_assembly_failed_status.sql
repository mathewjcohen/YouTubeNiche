-- migrations/013_assembly_failed_status.sql
-- Add 'assembly_failed' to the scripts status check constraint.
-- This status is set when video assembly permanently fails (e.g. S3 audio missing)
-- so the voiceover agent does not requeue the script and burn API quota.
ALTER TABLE scripts DROP CONSTRAINT IF EXISTS scripts_status_check;
ALTER TABLE scripts ADD CONSTRAINT scripts_status_check
  CHECK (status IN ('pending','awaiting_review','approved','rejected','processing','done','assembly_failed'));
