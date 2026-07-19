-- Central multi-machine runner config/control.
-- Runners use these rows to converge Mac 1, Mac 2, and later cloud workers without SSH.

create table if not exists fleet_config (
  key        text primary key,
  value      text not null,
  note       text,
  updated_by text,
  updated_at timestamptz not null default now()
);

alter table fleet_config add column if not exists value text;
alter table fleet_config add column if not exists note text;
alter table fleet_config add column if not exists updated_by text;
alter table fleet_config add column if not exists updated_at timestamptz not null default now();

create table if not exists fleet_control (
  id           uuid primary key default gen_random_uuid(),
  action       text not null check (action in ('restart', 'git_pull', 'reload_config')),
  target       text not null default 'all',
  params       jsonb not null default '{}'::jsonb,
  handled_by   text[] not null default '{}',
  done         boolean not null default false,
  attempts     int not null default 0,
  last_error   text,
  requested_by text,
  requested_at timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

alter table fleet_control add column if not exists action text;
alter table fleet_control add column if not exists target text not null default 'all';
alter table fleet_control add column if not exists params jsonb not null default '{}'::jsonb;
alter table fleet_control add column if not exists handled_by text[] not null default '{}';
alter table fleet_control add column if not exists done boolean not null default false;
alter table fleet_control add column if not exists attempts int not null default 0;
alter table fleet_control add column if not exists last_error text;
alter table fleet_control add column if not exists requested_by text;
alter table fleet_control add column if not exists requested_at timestamptz not null default now();
alter table fleet_control add column if not exists updated_at timestamptz not null default now();

create index if not exists fleet_control_open_idx
  on fleet_control(done, requested_at);

alter table fleet_config enable row level security;
alter table fleet_control enable row level security;

do $$
begin
  execute 'drop policy if exists fleet_config_auth_read on fleet_config';
  execute 'create policy fleet_config_auth_read on fleet_config for select to authenticated using (true)';
  execute 'drop policy if exists fleet_config_auth_write on fleet_config';
  execute 'create policy fleet_config_auth_write on fleet_config for all to authenticated using (true) with check (true)';
  execute 'drop policy if exists fleet_control_auth_read on fleet_control';
  execute 'create policy fleet_control_auth_read on fleet_control for select to authenticated using (true)';
  execute 'drop policy if exists fleet_control_auth_write on fleet_control';
  execute 'create policy fleet_control_auth_write on fleet_control for all to authenticated using (true) with check (true)';
end $$;

do $$
begin
  begin execute 'alter publication supabase_realtime add table fleet_config'; exception when others then null; end;
  begin execute 'alter publication supabase_realtime add table fleet_control'; exception when others then null; end;
end $$;

insert into fleet_config(key, value, note, updated_by)
values
  ('ORCH_AUTO_PULL', 'true', 'Every runner periodically fast-forwards to pushed orchestrator code.', 'migration'),
  ('ORCH_AUTO_PULL_RESTART', 'true', 'Restart after a successful auto-pull so new code is active.', 'migration'),
  ('ORCH_AUTO_PULL_MIN', '2', 'Mac-to-Mac propagation polling cadence in minutes.', 'migration'),
  ('ORCH_FLEET_TICK_S', '30', 'How often runners read central config/control rows.', 'migration'),
  ('ORCH_KEEPALIVE_STAY_RESIDENT', 'true', 'Keep launchd supervisor resident instead of churning duplicate starts.', 'migration')
on conflict (key) do update set
  value = excluded.value,
  note = excluded.note,
  updated_by = excluded.updated_by,
  updated_at = now();

select '0033_fleet_control OK – ' || count(*) || ' config rows, '
       || (select count(*) from fleet_control) || ' control rows'
  as status
  from fleet_config;
