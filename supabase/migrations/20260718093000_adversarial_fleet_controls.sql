-- #26-#33: append-only evidence surfaces for bounded autonomous control.
create table if not exists fleet_signal_snapshots (
  id bigint generated always as identity primary key, app text not null default 'ORCHESTRATOR',
  queue_growth numeric not null default 0, latency_drift numeric not null default 0,
  budget_burn numeric not null default 0, created_at timestamptz not null default now()
);
-- Optional cohort summaries turn the existing A/B engine's before/after lift into DiD.
alter table committee_experiments add column if not exists control_metric_start numeric;
alter table committee_experiments add column if not exists control_metric_last numeric;
alter table committee_experiments add column if not exists treatment_cohort text;
alter table committee_experiments add column if not exists control_cohort text;

-- Canonical evidence fabric.  Events are immutable and safely replayable.
create table if not exists fleet_evidence_events (
  id bigint generated always as identity primary key,
  app text not null default 'ORCHESTRATOR', kind text not null, subject text not null,
  payload jsonb not null default '{}'::jsonb, parent_key text,
  idempotency_key text not null unique, observed_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create index if not exists fleet_evidence_kind_created_idx on fleet_evidence_events(kind, created_at desc);
create index if not exists fleet_evidence_app_created_idx on fleet_evidence_events(app, created_at desc);

-- Only compiler-authorized config changes can be replicated by fleet clients.
create table if not exists policy_config_changes (
  id text primary key, config_key text not null, candidate_value text not null, actor text,
  status text not null check (status in ('authorized','rejected','graduated','rolled_back')),
  simulation jsonb not null default '{}'::jsonb, metrics jsonb not null default '{}'::jsonb,
  outcome text, evidence_key text, created_at timestamptz not null default now(), decided_at timestamptz
);
alter table fleet_config add column if not exists policy_change_id text references policy_config_changes(id);
create index if not exists fleet_config_policy_idx on fleet_config(policy_change_id);
insert into policy_config_changes(id, config_key, candidate_value, actor, status, simulation, metrics, outcome)
select 'legacy-' || md5(key || '=' || value), key, value, 'migration', 'graduated',
       '{"legacy":true}'::jsonb, '{}'::jsonb, 'pre-policy baseline'
from fleet_config where policy_change_id is null
on conflict (id) do nothing;
update fleet_config set policy_change_id = 'legacy-' || md5(key || '=' || value)
where policy_change_id is null;
create or replace function enforce_compiled_fleet_config() returns trigger language plpgsql as $$
begin
  if new.policy_change_id is null then
    raise exception 'fleet_config writes require an authorized policy change';
  end if;
  if not exists (select 1 from policy_config_changes p where p.id = new.policy_change_id
                 and p.config_key = new.key and p.candidate_value = new.value
                 and p.status in ('authorized','graduated')) then
    raise exception 'fleet_config policy change is missing, mismatched, or not authorized';
  end if;
  return new;
end $$;
drop trigger if exists fleet_config_compiled_only on fleet_config;
create trigger fleet_config_compiled_only before insert or update on fleet_config
  for each row execute function enforce_compiled_fleet_config();

create table if not exists fleet_app_audits (
  id bigint generated always as identity primary key, app text not null, repo text not null,
  missing jsonb not null default '[]'::jsonb, status text not null, created_at timestamptz not null default now()
);
create table if not exists tenant_meta_initializations (
  id bigint generated always as identity primary key, tenant_id text not null, observation_count integer not null,
  dp_epsilon numeric, global_model_version text, initialization jsonb not null,
  status text not null default 'advisory', created_at timestamptz not null default now()
);
create table if not exists compute_auction_rounds (
  id text primary key, bids jsonb not null, allocation jsonb not null, reserve_price numeric not null default 0,
  status text not null default 'advisory', created_at timestamptz not null default now()
);
create table if not exists constitutional_amendment_proposals (
  id bigint generated always as identity primary key, rule text not null, evidence jsonb not null,
  status text not null default 'proposed' check (status in ('proposed','approved','rejected')),
  approved_by text, created_at timestamptz not null default now(), decided_at timestamptz
);
create table if not exists high_stakes_debates (
  id text primary key, subject_type text, subject_id text, blast_radius numeric not null,
  proposals jsonb not null, critiques jsonb not null, judgment jsonb not null, dissent jsonb not null default '[]'::jsonb,
  status text not null default 'completed', created_at timestamptz not null default now()
);
create table if not exists compliance_receipts (
  id bigint generated always as identity primary key, app text not null default 'ORCHESTRATOR',
  control text not null, valid boolean not null default true, evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create table if not exists compliance_control_requirements (
  id bigint generated always as identity primary key, app text not null default 'ORCHESTRATOR',
  control text not null, sla_coverage numeric not null default 1, unique(app, control)
);
create table if not exists continuous_compliance_status (
  id bigint generated always as identity primary key, app text not null, coverage numeric not null,
  missing jsonb not null default '[]'::jsonb, checked_at timestamptz not null default now()
);
create table if not exists compliance_remediations (
  id bigint generated always as identity primary key, app text not null, missing_controls jsonb not null,
  status text not null default 'open', created_at timestamptz not null default now()
);
alter table fleet_signal_snapshots enable row level security;
alter table compliance_receipts enable row level security;
alter table compliance_control_requirements enable row level security;
alter table continuous_compliance_status enable row level security;
alter table compliance_remediations enable row level security;
alter table fleet_evidence_events enable row level security;
alter table policy_config_changes enable row level security;
alter table fleet_app_audits enable row level security;
alter table tenant_meta_initializations enable row level security;
alter table compute_auction_rounds enable row level security;
alter table constitutional_amendment_proposals enable row level security;
alter table high_stakes_debates enable row level security;
