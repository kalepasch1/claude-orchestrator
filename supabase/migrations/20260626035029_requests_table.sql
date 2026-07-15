
-- User/support request signals for demand_mining.py
create table if not exists requests (
  id          uuid primary key default gen_random_uuid(),
  project     text not null,
  text        text not null,
  source      text,          -- e.g. 'slack', 'support', 'github-issue'
  created_at  timestamptz not null default now()
);
alter table requests enable row level security;
create policy "requests_auth_read"   on requests for select using (auth.role() = 'authenticated');
create policy "requests_auth_write"  on requests for insert with check (auth.role() = 'authenticated');
alter publication supabase_realtime add table requests;
;
