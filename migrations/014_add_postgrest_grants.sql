-- Explicit PostgREST grants for all public schema tables.
-- Required for Supabase Data API access on new projects after May 30, 2026.
-- Also enables RLS on all tables (previously missing) with permissive policies
-- for authenticated users, preserving existing access patterns.

-- ── RLS + grants for pipeline tables ────────────────────────────────────────────
-- This is a single-owner pipeline app; authenticated = the owner managing the dashboard.
-- No per-row user isolation needed — RLS policies are permissive for authenticated.

alter table public.niches enable row level security;
create policy "authenticated_full_access" on public.niches for all to authenticated using (true) with check (true);
grant select, insert, update, delete on public.niches to authenticated;
grant select, insert, update, delete on public.niches to service_role;

alter table public.topics enable row level security;
create policy "authenticated_full_access" on public.topics for all to authenticated using (true) with check (true);
grant select, insert, update, delete on public.topics to authenticated;
grant select, insert, update, delete on public.topics to service_role;

alter table public.scripts enable row level security;
create policy "authenticated_full_access" on public.scripts for all to authenticated using (true) with check (true);
grant select, insert, update, delete on public.scripts to authenticated;
grant select, insert, update, delete on public.scripts to service_role;

alter table public.videos enable row level security;
create policy "authenticated_full_access" on public.videos for all to authenticated using (true) with check (true);
grant select, insert, update, delete on public.videos to authenticated;
grant select, insert, update, delete on public.videos to service_role;

alter table public.gate_config enable row level security;
create policy "authenticated_read" on public.gate_config for select to authenticated using (true);
grant select on public.gate_config to authenticated;
grant select, insert, update, delete on public.gate_config to service_role;

alter table public.niche_analytics enable row level security;
create policy "authenticated_read" on public.niche_analytics for select to authenticated using (true);
grant select on public.niche_analytics to authenticated;
grant select, insert, update, delete on public.niche_analytics to service_role;

-- youtube_accounts: contains OAuth tokens — never expose to authenticated clients
alter table public.youtube_accounts enable row level security;
grant select, insert, update, delete on public.youtube_accounts to service_role;

alter table public.published_videos enable row level security;
create policy "authenticated_read" on public.published_videos for select to authenticated using (true);
grant select on public.published_videos to authenticated;
grant select, insert, update, delete on public.published_videos to service_role;

alter table public.video_analytics enable row level security;
create policy "authenticated_read" on public.video_analytics for select to authenticated using (true);
grant select on public.video_analytics to authenticated;
grant select, insert, update, delete on public.video_analytics to service_role;

alter table public.insights enable row level security;
create policy "authenticated_read" on public.insights for select to authenticated using (true);
grant select on public.insights to authenticated;
grant select, insert, update, delete on public.insights to service_role;

alter table public.niche_score_history enable row level security;
create policy "authenticated_read" on public.niche_score_history for select to authenticated using (true);
grant select on public.niche_score_history to authenticated;
grant select, insert, update, delete on public.niche_score_history to service_role;
