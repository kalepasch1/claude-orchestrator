-- Event-driven, cross-host native delivery proof fabric (additive/idempotent).
alter table tasks add column if not exists execution_lane text;
alter table tasks add column if not exists artifact_commit text;
alter table tasks add column if not exists artifact_branch text;
alter table tasks add column if not exists shadow_only boolean not null default false;
alter table tasks add column if not exists paired_trial_id uuid;

create table if not exists delivery_events (
  id uuid primary key default gen_random_uuid(), provider text not null,
  event_id text not null, event_type text not null, payload jsonb not null default '{}',
  state text not null default 'queued', attempts int not null default 0,
  available_at timestamptz not null default now(), claimed_by text, claimed_at timestamptz,
  error text, created_at timestamptz not null default now(), completed_at timestamptz,
  unique(provider,event_id)
);
create index if not exists delivery_events_claim_idx on delivery_events(state,available_at);

create table if not exists commit_manifests (
  id text primary key, project_id uuid references projects(id) on delete cascade,
  commit_sha text not null, parent_sha text, tree_sha text not null,
  symbols jsonb not null default '{}', files jsonb not null default '[]',
  created_at timestamptz not null default now(), unique(project_id,commit_sha)
);

create table if not exists native_verification_jobs (
  id uuid primary key default gen_random_uuid(), project_id uuid references projects(id) on delete cascade,
  commit_sha text not null, manifest_id text references commit_manifests(id),
  commands jsonb not null default '[]', image text, state text not null default 'queued',
  attempts int not null default 0, available_at timestamptz not null default now(),
  claimed_by text, claimed_at timestamptz, proof_digest text, result jsonb,
  created_at timestamptz not null default now(), completed_at timestamptz,
  unique(project_id,commit_sha,commands)
);
create index if not exists native_verification_jobs_claim_idx on native_verification_jobs(state,available_at);

create table if not exists native_paired_shadow_trials (
  id uuid primary key default gen_random_uuid(), source_task_id uuid references tasks(id) on delete set null,
  project_id uuid references projects(id) on delete cascade, base_sha text not null,
  status text not null default 'queued', cowork_task_id uuid references tasks(id) on delete set null,
  native_task_id uuid references tasks(id) on delete set null,
  cowork_result jsonb, native_result jsonb, created_at timestamptz not null default now(),
  completed_at timestamptz, unique(source_task_id,base_sha)
);

-- One transition contract for both executors. Consumers no longer need to
-- infer completion from runner-specific notes, and dormant DONE-without-proof
-- paths are visible immediately.
create table if not exists workflow_outcome_contracts (
  id bigint generated always as identity primary key,
  task_id uuid not null references tasks(id) on delete cascade,
  project_id uuid references projects(id) on delete set null,
  workflow text not null, from_state text, to_state text not null,
  artifact_commit text, verified boolean not null default false,
  integrated boolean not null default false, observed_at timestamptz not null default now()
);
create index if not exists workflow_outcome_contracts_task_idx
  on workflow_outcome_contracts(task_id,observed_at desc);

create or replace function emit_workflow_outcome_contract()
returns trigger language plpgsql security definer set search_path=public as $$
begin
  if old.state is distinct from new.state and new.state::text in ('DONE','MERGED','BLOCKED','TESTFAIL','CONFLICT') then
    insert into workflow_outcome_contracts(task_id,project_id,workflow,from_state,to_state,
      artifact_commit,verified,integrated)
    values(new.id,new.project_id,
      case when coalesce(new.execution_lane,'')='cowork' or coalesce(new.account,'') like 'cowork-%'
           then 'cowork' else 'orchestrator_native' end,
      old.state::text,new.state::text,new.artifact_commit,
      new.state::text in ('DONE','MERGED') and new.artifact_commit is not null,
      new.state::text='MERGED');
  end if;
  return new;
end $$;
drop trigger if exists tasks_workflow_outcome_contract on tasks;
create trigger tasks_workflow_outcome_contract after update of state on tasks
for each row execute function emit_workflow_outcome_contract();

create or replace function claim_delivery_event(p_runner text)
returns setof delivery_events language plpgsql security definer set search_path=public as $$
declare picked delivery_events;
begin
  select * into picked from delivery_events where state='queued' and available_at <= now()
  order by created_at for update skip locked limit 1;
  if picked.id is null then return; end if;
  update delivery_events set state='running',claimed_by=p_runner,claimed_at=now(),attempts=attempts+1
  where id=picked.id returning * into picked; return next picked;
end $$;

create or replace function claim_native_verification_job(p_runner text)
returns setof native_verification_jobs language plpgsql security definer set search_path=public as $$
declare picked native_verification_jobs;
begin
  select * into picked from native_verification_jobs where state='queued' and available_at <= now()
  order by created_at for update skip locked limit 1;
  if picked.id is null then return; end if;
  update native_verification_jobs set state='running',claimed_by=p_runner,claimed_at=now(),attempts=attempts+1
  where id=picked.id returning * into picked; return next picked;
end $$;

alter table delivery_events enable row level security;
alter table commit_manifests enable row level security;
alter table native_verification_jobs enable row level security;
alter table native_paired_shadow_trials enable row level security;
alter table workflow_outcome_contracts enable row level security;
grant execute on function claim_delivery_event(text) to service_role;
grant execute on function claim_native_verification_job(text) to service_role;
