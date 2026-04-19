-- migrations/003_pipeline_toggle.sql

-- Seed pipeline_enabled setting (default: on)
insert into app_settings (key, value)
values ('pipeline_enabled', 'true')
on conflict (key) do nothing;
