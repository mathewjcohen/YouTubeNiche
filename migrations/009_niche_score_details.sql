-- Store score component breakdown so dashboard can show why a niche ranked
ALTER TABLE niches ADD COLUMN IF NOT EXISTS score_details jsonb;
