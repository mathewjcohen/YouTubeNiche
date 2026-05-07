CREATE TABLE niche_score_history (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  niche_name text NOT NULL,
  category text NOT NULL,
  final_score float NOT NULL,
  score_details jsonb,
  recorded_at timestamptz DEFAULT now()
);

CREATE INDEX niche_score_history_lookup ON niche_score_history (niche_name, recorded_at);
