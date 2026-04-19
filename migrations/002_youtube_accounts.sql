-- migrations/002_youtube_accounts.sql

-- YouTube OAuth tokens, one row per channel
create table if not exists youtube_accounts (
  id uuid primary key default gen_random_uuid(),
  channel_name text not null,
  channel_id text unique,
  handle text,
  token_json jsonb not null,
  created_at timestamptz default now()
);

-- Link each niche to a YouTube channel
alter table niches
  add column if not exists youtube_account_id uuid references youtube_accounts(id),
  add column if not exists channel_state text not null default 'unconfigured'
    check (channel_state in ('unconfigured', 'linked'));
