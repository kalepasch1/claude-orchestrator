
-- central shared config: change once here, BOTH Macs load it into env every loop
create table if not exists fleet_config (
  key text primary key,
  value text,
  updated_at timestamptz not null default now(),
  updated_by text
);
-- central control channel: restart / pull / reload issued once, honored by the targeted host(s)
create table if not exists fleet_control (
  id bigint generated always as identity primary key,
  action text not null,                       -- restart | git_pull | reload_config
  target text not null default 'all',         -- hostname or 'all'
  params jsonb not null default '{}',
  requested_at timestamptz not null default now(),
  requested_by text,
  handled_by text[] not null default '{}',
  done boolean not null default false
);
create index if not exists fleet_control_open on fleet_control (done) where done = false;
alter table fleet_config enable row level security;
alter table fleet_control enable row level security;
-- Mission Control (authenticated) can read both + queue control actions
drop policy if exists fleet_config_read on fleet_config;
create policy fleet_config_read on fleet_config for select to authenticated using (true);
drop policy if exists fleet_control_read on fleet_control;
create policy fleet_control_read on fleet_control for select to authenticated using (true);
drop policy if exists fleet_control_insert on fleet_control;
create policy fleet_control_insert on fleet_control for insert to authenticated with check (true);
;
