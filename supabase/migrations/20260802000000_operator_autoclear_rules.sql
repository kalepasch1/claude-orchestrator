-- 20260802000000_operator_autoclear_rules.sql
-- Rule-based auto-clearing for operator approval cards.
-- This table stores rules that determine which operator/deploy/secret cards
-- are auto-approved based on project, kind, and optional max_usd threshold.

create table if not exists operator_autoclear_rules (
  id          text primary key,
  project     text,
  kind        text not null
                check (kind in ('operator', 'deploy', 'secret', 'legal')),
  max_usd     numeric,
  enabled     boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table operator_autoclear_rules add column if not exists id        text;
alter table operator_autoclear_rules add column if not exists project  text;
alter table operator_autoclear_rules add column if not exists kind     text;
alter table operator_autoclear_rules add column if not exists max_usd  numeric;
alter table operator_autoclear_rules add column if not exists enabled  boolean not null default true;
alter table operator_autoclear_rules add column if not exists created_at timestamptz not null default now();
alter table operator_autoclear_rules add column if not exists updated_at timestamptz not null default now();

create index if not exists operator_autoclear_rules_enabled_idx on operator_autoclear_rules(enabled);
create index if not exists operator_autoclear_rules_project_kind_idx on operator_autoclear_rules(project, kind, enabled);

-- ---------- RLS ----------
alter table operator_autoclear_rules enable row level security;

do $$ begin
  -- Service role (runner/fleet) can read all rules without RLS.
  -- This table is not exposed to authenticated users for now.
  -- Only allow service role full access.
end $$;

select '20260802000000_operator_autoclear_rules OK – table: operator_autoclear_rules' as status;
