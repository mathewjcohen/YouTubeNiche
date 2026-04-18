-- migrations/001_initial_schema.sql

-- Niches: one row per discovered or manually submitted niche
create table if not exists niches (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  category text not null,
  status text not null default 'candidate'
    check (status in ('candidate','testing','promoted','archived')),
  score numeric,
  rpm_min numeric,
  rpm_max numeric,
  subreddits text[] default '{}',
  niche_source text not null default 'scout'
    check (niche_source in ('scout','manual')),
  brand_package jsonb,
  gate1_state text default 'pending'
    check (gate1_state in ('pending','awaiting_review','approved','rejected')),
  activated_at timestamptz,
  review_due_at timestamptz,
  created_at timestamptz default now()
);

-- Topics: reddit posts scored as video candidates
create table if not exists topics (
  id uuid primary key default gen_random_uuid(),
  niche_id uuid not null references niches(id),
  reddit_post_id text not null unique,
  title text not null,
  url text not null,
  body text,
  upvotes integer default 0,
  claude_score numeric,
  status text not null default 'pending'
    check (status in ('pending','awaiting_review','approved','rejected','processing','done')),
  gate2_state text default 'pending'
    check (gate2_state in ('pending','awaiting_review','approved','rejected')),
  rejection_reason text,
  created_at timestamptz default now()
);

-- Scripts: long-form + Short for each approved topic
create table if not exists scripts (
  id uuid primary key default gen_random_uuid(),
  topic_id uuid not null references topics(id),
  niche_id uuid not null references niches(id),
  long_form_text text,
  short_text text,
  youtube_title text,
  youtube_description text,
  youtube_tags text[],
  status text not null default 'pending'
    check (status in ('pending','awaiting_review','approved','rejected','processing','done')),
  gate3_state text default 'awaiting_review'
    check (gate3_state in ('pending','awaiting_review','approved','rejected')),
  rejection_reason text,
  created_at timestamptz default now()
);

-- Videos: one row tracks audio + video + thumbnail + upload state
create table if not exists videos (
  id uuid primary key default gen_random_uuid(),
  script_id uuid not null references scripts(id),
  niche_id uuid not null references niches(id),
  video_type text not null default 'long'
    check (video_type in ('long','short')),
  audio_path text,
  srt_path text,
  video_path text,
  thumbnail_path text,
  youtube_video_id text,
  status text not null default 'pending'
    check (status in ('pending','processing','awaiting_review','approved','rejected','uploaded')),
  gate4_state text default 'pending'
    check (gate4_state in ('pending','awaiting_review','approved','rejected')),
  gate5_state text default 'awaiting_review'
    check (gate5_state in ('pending','awaiting_review','approved','rejected')),
  gate6_state text default 'awaiting_review'
    check (gate6_state in ('pending','awaiting_review','approved','rejected')),
  gate4_rejection_reason text,
  gate5_rejection_reason text,
  gate6_rejection_reason text,
  created_at timestamptz default now(),
  published_at timestamptz
);

-- Gate config: global defaults + per-niche overrides (niche_id null = global)
create table if not exists gate_config (
  id uuid primary key default gen_random_uuid(),
  niche_id uuid references niches(id),
  gate_number integer not null check (gate_number between 1 and 6),
  enabled boolean not null default true,
  updated_at timestamptz default now(),
  unique (niche_id, gate_number)
);

-- Insert global defaults (Gates 1,3,5,6 ON; Gates 2,4 OFF)
insert into gate_config (niche_id, gate_number, enabled) values
  (null, 1, true),
  (null, 2, false),
  (null, 3, true),
  (null, 4, false),
  (null, 5, true),
  (null, 6, true)
on conflict (niche_id, gate_number) do nothing;

-- Niche analytics: weekly performance snapshots
create table if not exists niche_analytics (
  id uuid primary key default gen_random_uuid(),
  niche_id uuid not null references niches(id),
  polled_at timestamptz default now(),
  views_total integer default 0,
  ctr numeric,
  avg_watch_time_pct numeric,
  subs_total integer default 0,
  estimated_revenue_usd numeric,
  early_promotion_flagged boolean default false
);

-- Indexes
create index if not exists idx_topics_niche_status on topics(niche_id, status);
create index if not exists idx_scripts_niche_status on scripts(niche_id, status);
create index if not exists idx_videos_niche_status on videos(niche_id, status);
create index if not exists idx_analytics_niche on niche_analytics(niche_id, polled_at desc);
