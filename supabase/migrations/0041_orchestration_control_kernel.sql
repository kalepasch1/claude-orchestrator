-- Additive, online control kernel: objective reservations, event-sourced leases,
-- activation proofs, and causal product observations.
create table if not exists objective_claims (
  project_id uuid not null references projects(id) on delete cascade,
  objective_fingerprint text not null,
  lease_token uuid not null default gen_random_uuid(),
  lease_owner text not null,
  lease_until timestamptz not null,
  task_id uuid references tasks(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (project_id, objective_fingerprint)
);

create or replace function reserve_task_objective(
  p_project_id uuid, p_objective_fingerprint text, p_owner text, p_ttl_seconds int default 120
) returns table(accepted boolean, lease_token uuid, existing_task_id uuid)
language plpgsql security definer set search_path=public as $$
declare v_token uuid := gen_random_uuid(); v_row objective_claims%rowtype;
begin
  insert into objective_claims(project_id, objective_fingerprint, lease_token, lease_owner, lease_until)
  values(p_project_id, p_objective_fingerprint, v_token, p_owner,
         now() + make_interval(secs => greatest(15, p_ttl_seconds)))
  on conflict(project_id, objective_fingerprint) do update
    set lease_token=excluded.lease_token, lease_owner=excluded.lease_owner,
        lease_until=excluded.lease_until, updated_at=now()
    where objective_claims.task_id is null and objective_claims.lease_until < now();
  select * into v_row from objective_claims
    where project_id=p_project_id and objective_fingerprint=p_objective_fingerprint;
  return query select v_row.lease_token=v_token, v_row.lease_token, v_row.task_id;
end $$;

create or replace function finalize_task_objective(
  p_project_id uuid, p_objective_fingerprint text, p_lease_token uuid, p_task_id uuid
) returns boolean language plpgsql security definer set search_path=public as $$
begin
  update objective_claims set task_id=p_task_id, lease_until='infinity', updated_at=now()
   where project_id=p_project_id and objective_fingerprint=p_objective_fingerprint
     and lease_token=p_lease_token and task_id is null;
  return found;
end $$;

create table if not exists actuator_leases (
  actuator text primary key, owner text not null, lease_token uuid not null,
  lease_until timestamptz not null, acquired_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists actuator_events (
  id bigint generated always as identity primary key, actuator text not null,
  owner text not null, lease_token uuid, event text not null,
  success boolean, detail jsonb not null default '{}', at timestamptz not null default now()
);
create index if not exists actuator_events_actuator_at_idx on actuator_events(actuator, at desc);

create or replace function acquire_actuator_lease(
  p_actuator text, p_owner text, p_ttl_seconds int default 300
) returns table(acquired boolean, lease_token uuid, lease_until timestamptz)
language plpgsql security definer set search_path=public as $$
declare v_token uuid := gen_random_uuid(); v_row actuator_leases%rowtype;
begin
  insert into actuator_leases(actuator,owner,lease_token,lease_until)
  values(p_actuator,p_owner,v_token,now()+make_interval(secs=>greatest(15,p_ttl_seconds)))
  on conflict(actuator) do update set owner=excluded.owner,lease_token=excluded.lease_token,
    lease_until=excluded.lease_until,updated_at=now()
    where actuator_leases.lease_until < now() or actuator_leases.owner=p_owner;
  select * into v_row from actuator_leases where actuator=p_actuator;
  insert into actuator_events(actuator,owner,lease_token,event,success,detail)
    values(p_actuator,p_owner,v_token,'acquire',v_row.lease_token=v_token,
           jsonb_build_object('lease_until',v_row.lease_until));
  return query select v_row.lease_token=v_token,v_row.lease_token,v_row.lease_until;
end $$;

create table if not exists capability_activation_events (
  id bigint generated always as identity primary key, capability text not null,
  stage text not null check(stage in ('invocation','effect','outcome')),
  success boolean not null, trace_id uuid not null default gen_random_uuid(),
  task_id uuid references tasks(id) on delete set null, artifact_id text,
  detail jsonb not null default '{}', at timestamptz not null default now()
);
create index if not exists capability_activation_at_idx on capability_activation_events(capability,at desc);

create table if not exists product_metric_events (
  id bigint generated always as identity primary key, project_id uuid references projects(id) on delete cascade,
  task_id uuid references tasks(id) on delete set null, release_id uuid,
  experiment text not null, metric text not null, variant text not null,
  subject_hash text, value double precision not null, guardrail boolean not null default false,
  metadata jsonb not null default '{}', observed_at timestamptz not null default now()
);
create index if not exists product_metric_experiment_idx
  on product_metric_events(experiment,metric,variant,observed_at desc);

alter table objective_claims enable row level security;
alter table actuator_leases enable row level security;
alter table actuator_events enable row level security;
alter table capability_activation_events enable row level security;
alter table product_metric_events enable row level security;

revoke all on function reserve_task_objective(uuid,text,text,int) from public;
revoke all on function finalize_task_objective(uuid,text,uuid,uuid) from public;
revoke all on function acquire_actuator_lease(text,text,int) from public;
grant execute on function reserve_task_objective(uuid,text,text,int) to service_role;
grant execute on function finalize_task_objective(uuid,text,uuid,uuid) to service_role;
grant execute on function acquire_actuator_lease(text,text,int) to service_role;
