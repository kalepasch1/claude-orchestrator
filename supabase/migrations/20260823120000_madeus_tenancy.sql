-- 20260823120000_madeus_tenancy.sql
--
-- Tenancy for the orchestrator: an org boundary around projects, tasks,
-- approvals, steering events, deployment bindings, quotas and usage.
--
-- THE CONSTRAINT THAT SHAPES THIS MIGRATION
-- -----------------------------------------
-- There is a live single-operator fleet running against these tables right now.
-- A migration that makes tenant_id NOT NULL, or that adds a restrictive RLS
-- policy to `tasks`, stops that fleet mid-run. So every column added here is
-- NULLABLE with a founding-tenant DEFAULT, and every backfill is idempotent:
-- existing rows join the founding tenant, and existing code that never mentions
-- a tenant keeps working unchanged. That is the "no regression for the existing
-- portfolio" half of the proof line, and it is a hard requirement, not a nicety.
--
-- RLS FOLLOWS IN A SECOND MIGRATION, DELIBERATELY
-- -----------------------------------------------
-- Enabling RLS on `tasks` before every writer carries a tenant would fail the
-- fleet closed — which is the right default for a NEW table (see
-- madeus_hivemind_* in web/supabase/migrations/002) and the wrong one for a
-- table with live traffic. The new tenant-owned tables below DO get RLS now,
-- because nothing depends on them yet.
--
-- Idempotent throughout, per repo convention.

-- ── The org boundary ────────────────────────────────────────────────────────

create table if not exists tenants (
  tenant_id     text primary key,
  display_name  text not null,
  -- 'strict' | 'shared_readonly'; mirrors IsolationMode in
  -- web/types/madeus-embed.ts. strict means an unscoped read returns nothing.
  isolation     text not null default 'strict',
  -- The founding tenant is the existing single-operator portfolio. Exactly one
  -- row may carry this flag; see the unique index below.
  is_founding   boolean not null default false,
  created_at    timestamptz not null default now()
);

-- One founding tenant, enforced rather than assumed: a second one would make
-- "the default tenant" ambiguous for every backfill in this file.
create unique index if not exists tenants_single_founding
  on tenants (is_founding) where is_founding;

insert into tenants (tenant_id, display_name, isolation, is_founding)
values ('founding', 'Founding portfolio (single-operator fleet)', 'strict', true)
on conflict (tenant_id) do nothing;

-- ── Scoping the existing tables ─────────────────────────────────────────────
--
-- Nullable + default + backfill, in that order, so a concurrent writer that
-- omits tenant_id lands in the founding tenant instead of failing.

do $$
declare
  t text;
begin
  foreach t in array array['projects', 'tasks', 'approvals', 'steering_events']
  loop
    if exists (select 1 from information_schema.tables
               where table_schema = 'public' and table_name = t) then
      execute format(
        'alter table %I add column if not exists tenant_id text default ''founding''', t);
      execute format(
        'update %I set tenant_id = ''founding'' where tenant_id is null', t);
      execute format(
        'create index if not exists %I on %I (tenant_id)', 'idx_' || t || '_tenant', t);
      -- FK last: it is the part most likely to fail on a table with odd rows,
      -- and failing here must not lose the column + backfill above.
      begin
        execute format(
          'alter table %I add constraint %I foreign key (tenant_id) '
          'references tenants(tenant_id) on delete restrict',
          t, t || '_tenant_fk');
      exception
        when duplicate_object then null;
        when others then
          raise notice 'tenant FK on % skipped: %', t, sqlerrm;
      end;
    else
      raise notice 'table % not present; skipped', t;
    end if;
  end loop;
end $$;

-- ── Deployment bindings move out of JSON ────────────────────────────────────
--
-- runner/deployment_bindings.json stays on disk as the SEED for the founding
-- tenant (and as the offline fallback when the DB is unreachable — the fleet
-- must not become unable to find its own repos because Supabase blinked).
-- The table is the source of truth once seeded.

create table if not exists tenant_deployment_bindings (
  tenant_id            text not null references tenants(tenant_id) on delete cascade,
  app                  text not null,
  repo_path            text not null,
  github_repo          text not null,
  branch               text not null default 'main',
  vercel_project       text,
  supabase_project_ref text,
  created_at           timestamptz not null default now(),
  primary key (tenant_id, app)
);
create index if not exists idx_tenant_bindings_tenant on tenant_deployment_bindings (tenant_id);

-- A repo path belongs to exactly ONE tenant. This is the schema-level half of
-- the execution-isolation requirement: without it, two tenants could both claim
-- /Users/.../apparently and a worker resolving by path could hand tenant B a
-- checkout tenant A is mid-write on.
create unique index if not exists tenant_bindings_repo_path_unique
  on tenant_deployment_bindings (repo_path);

-- ── Quotas and usage metering ───────────────────────────────────────────────

create table if not exists tenant_quotas (
  tenant_id            text primary key references tenants(tenant_id) on delete cascade,
  max_tasks_per_day    integer not null default 0,   -- 0 = unlimited
  max_model_spend_usd  numeric(12,4) not null default 0,
  max_machines         integer not null default 0,
  updated_at           timestamptz not null default now()
);

-- The founding tenant is explicitly unlimited: introducing tenancy must not
-- quietly throttle the fleet that already exists.
insert into tenant_quotas (tenant_id, max_tasks_per_day, max_model_spend_usd, max_machines)
values ('founding', 0, 0, 0)
on conflict (tenant_id) do nothing;

-- Usage is metered per day so a quota check is one indexed row read, not an
-- aggregate over the whole task history.
create table if not exists tenant_usage (
  tenant_id       text not null references tenants(tenant_id) on delete cascade,
  usage_date      date not null default current_date,
  tasks_run       integer not null default 0,
  model_spend_usd numeric(12,4) not null default 0,
  machines_seen   integer not null default 0,
  updated_at      timestamptz not null default now(),
  primary key (tenant_id, usage_date)
);
create index if not exists idx_tenant_usage_date on tenant_usage (usage_date desc);

-- ── Isolation on the NEW tables only ────────────────────────────────────────
--
-- These have no live traffic, so they can fail closed immediately. Reads are
-- granted to authenticated callers; writes stay service-role only, which is how
-- the runner already talks to this database.

alter table tenants                   enable row level security;
alter table tenant_deployment_bindings enable row level security;
alter table tenant_quotas             enable row level security;
alter table tenant_usage              enable row level security;

drop policy if exists tenants_read on tenants;
create policy tenants_read on tenants for select to authenticated using (true);

drop policy if exists tenant_bindings_read on tenant_deployment_bindings;
create policy tenant_bindings_read on tenant_deployment_bindings
  for select to authenticated using (true);

drop policy if exists tenant_quotas_read on tenant_quotas;
create policy tenant_quotas_read on tenant_quotas for select to authenticated using (true);

drop policy if exists tenant_usage_read on tenant_usage;
create policy tenant_usage_read on tenant_usage for select to authenticated using (true);
