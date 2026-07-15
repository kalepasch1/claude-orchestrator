-- Canonical, lane-neutral delivery contracts and remotely claimable verification.
alter table tasks add column if not exists execution_lane text;
alter table tasks add column if not exists artifact_branch text;
alter table tasks add column if not exists artifact_commit text;
alter table tasks add column if not exists artifact_id text;
alter table tasks add column if not exists paired_trial_key text;
alter table tasks add column if not exists shadow_only boolean not null default false;

create table if not exists workflow_outcome_contracts (
  id bigint generated always as identity primary key,
  transition_key text not null unique,
  task_id uuid not null references tasks(id) on delete cascade,
  project_id uuid references projects(id) on delete cascade,
  lane text not null,
  from_state text,
  to_state text not null,
  stage text not null,
  artifact_id text,
  artifact_branch text,
  contract jsonb not null default '{}',
  observed_at timestamptz not null default now()
);
create index if not exists workflow_outcome_lane_at_idx
  on workflow_outcome_contracts(lane, observed_at desc);

create or replace function emit_workflow_outcome_contract() returns trigger
language plpgsql security definer set search_path=public as $$
declare v_lane text; v_stage text; v_key text;
begin
  if tg_op='UPDATE' and old.state is not distinct from new.state then return new; end if;
  v_lane := coalesce(new.execution_lane,
    case when coalesce(new.account,'') ilike 'cowork%' then 'cowork'
         when coalesce(new.account,'') in ('parallel-swarm','orchestrator-native') then 'orchestrator_native'
         else 'orchestrator' end);
  v_stage := case new.state::text when 'DONE' then 'verified' when 'MERGED' then 'integrated'
    when 'BLOCKED' then 'failed' when 'RUNNING' then 'attempted' else lower(new.state::text) end;
  v_key := new.id::text || ':' || coalesce(case when tg_op='UPDATE' then old.state::text end,'') ||
           '>' || new.state::text || ':' || extract(epoch from coalesce(new.updated_at,now()))::text;
  insert into workflow_outcome_contracts(
    transition_key,task_id,project_id,lane,from_state,to_state,stage,
    artifact_id,artifact_branch,contract,observed_at)
  values(v_key,new.id,new.project_id,v_lane,
    case when tg_op='UPDATE' then old.state::text end,new.state::text,v_stage,new.artifact_id,new.artifact_branch,
    jsonb_build_object('task_id',new.id,'project_id',new.project_id,'lane',v_lane,
      'stage',v_stage,'state',new.state,'artifact_id',new.artifact_id,
      'artifact_branch',new.artifact_branch),coalesce(new.updated_at,now()))
  on conflict(transition_key) do nothing;
  return new;
end $$;
drop trigger if exists tasks_emit_workflow_outcome on tasks;
create trigger tasks_emit_workflow_outcome after insert or update of state on tasks
for each row execute function emit_workflow_outcome_contract();

create or replace function emit_release_outcome_contract() returns trigger
language plpgsql security definer set search_path=public as $$
declare t tasks%rowtype; v_lane text;
begin
  if new.deploy_status <> 'success' or (tg_op='UPDATE' and old.deploy_status='success') then return new; end if;
  for t in select * from tasks where artifact_commit=new.to_sha loop
    v_lane:=coalesce(t.execution_lane,case when coalesce(t.account,'') ilike 'cowork%' then 'cowork' else 'orchestrator' end);
    insert into workflow_outcome_contracts(transition_key,task_id,project_id,lane,from_state,to_state,
      stage,artifact_id,artifact_branch,contract,observed_at)
    values('release:'||new.id::text||':'||t.id::text,t.id,t.project_id,v_lane,t.state::text,t.state::text,
      'deployed',t.artifact_id,t.artifact_branch,jsonb_build_object('task_id',t.id,'project_id',t.project_id,
      'lane',v_lane,'stage','deployed','release_id',new.id,'commit',new.to_sha,'url',new.vercel_url),
      coalesce(new.deployed_at,now())) on conflict(transition_key) do nothing;
  end loop;
  return new;
end $$;
drop trigger if exists releases_emit_workflow_outcome on releases;
create trigger releases_emit_workflow_outcome after insert or update of deploy_status on releases
for each row execute function emit_release_outcome_contract();

create table if not exists verification_jobs (
  id uuid primary key default gen_random_uuid(), action_digest text not null unique,
  project_id uuid references projects(id) on delete cascade, task_id uuid references tasks(id) on delete set null,
  repository text not null, commit_sha text not null, command text not null,
  oci_image text, state text not null default 'QUEUED', lease_owner text,
  lease_until timestamptz, result_digest text, result jsonb,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists verification_jobs_claim_idx on verification_jobs(state,created_at);
create or replace function claim_verification_job(p_owner text,p_ttl_seconds int default 900)
returns setof verification_jobs language plpgsql security definer set search_path=public as $$
declare v_id uuid;
begin
 select id into v_id from verification_jobs where state='QUEUED' or
   (state='RUNNING' and lease_until<now()) order by created_at for update skip locked limit 1;
 if v_id is null then return; end if;
 return query update verification_jobs set state='RUNNING',lease_owner=p_owner,
   lease_until=now()+make_interval(secs=>greatest(60,p_ttl_seconds)),updated_at=now()
   where id=v_id returning *;
end $$;

create table if not exists paired_shadow_trials (
  trial_key text not null, lane text not null, task_id uuid references tasks(id) on delete set null,
  base_sha text, artifact_id text, passed boolean not null, duration_ms bigint,
  value_per_hour double precision, detail jsonb not null default '{}', observed_at timestamptz not null default now(),
  primary key(trial_key,lane)
);
alter table workflow_outcome_contracts enable row level security;
alter table verification_jobs enable row level security;
alter table paired_shadow_trials enable row level security;
revoke all on function claim_verification_job(text,int) from public;
grant execute on function claim_verification_job(text,int) to service_role;
