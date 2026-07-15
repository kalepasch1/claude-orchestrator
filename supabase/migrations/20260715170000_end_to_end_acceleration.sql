-- Cross-host acceleration, activation proofs, and causal pathway trials.
create table if not exists pathway_decisions (id bigint generated always as identity primary key, task_id uuid references tasks(id) on delete cascade, project_id uuid references projects(id) on delete cascade, lane text not null check (lane in ('cowork','orchestrator_native')), reason text not null, cowork_exhausted boolean not null default false, paid_api_eligible boolean not null default false, detail jsonb not null default '{}', created_at timestamptz not null default now());
create index if not exists pathway_decisions_task_idx on pathway_decisions(task_id,created_at desc);
alter table commit_manifests add column if not exists changed_files jsonb not null default '[]';
alter table commit_manifests add column if not exists parse_ms bigint;
create table if not exists verification_cache_entries (cache_key text primary key, success boolean not null, result jsonb not null default '{}', host text, created_at timestamptz not null default now(), completed_at timestamptz not null default now());
create table if not exists capability_activation_proofs (id bigint generated always as identity primary key, task_id uuid references tasks(id) on delete cascade, project_id uuid references projects(id) on delete cascade, capability text not null, invocation_key text not null, invoked boolean not null default true, effect boolean not null default false, outcome text, metrics jsonb not null default '{}', created_at timestamptz not null default now(), unique(capability,invocation_key));
create index if not exists activation_proofs_task_idx on capability_activation_proofs(task_id,created_at desc);
create table if not exists proof_batches (id text primary key, project_id uuid references projects(id) on delete cascade, base_sha text not null, candidate_sha text, artifact_commits jsonb not null default '[]', files jsonb not null default '[]', test_cmd text, proof_digest text, state text not null default 'prepared', duration_ms bigint, created_at timestamptz not null default now(), completed_at timestamptz);
alter table native_paired_shadow_trials add column if not exists prompt_hash text;
alter table native_paired_shadow_trials add column if not exists frozen_prompt text;
alter table native_paired_shadow_trials add column if not exists cowork_value_per_hour double precision;
alter table native_paired_shadow_trials add column if not exists native_value_per_hour double precision;
alter table pathway_decisions enable row level security;
alter table verification_cache_entries enable row level security;
alter table capability_activation_proofs enable row level security;
alter table proof_batches enable row level security;
create or replace function native_promotion_evidence(p_min_pairs int default 30) returns table(completed_pairs bigint,native_wins bigint,cowork_wins bigint,native_win_rate double precision,wilson_lower_bound double precision,value_hour_ratio double precision,eligible boolean) language sql stable security definer set search_path=public as $$ with s as (select count(*)::bigint n,count(*) filter (where native_value_per_hour>cowork_value_per_hour)::bigint nw,count(*) filter (where cowork_value_per_hour>native_value_per_hour)::bigint cw,coalesce(sum(native_value_per_hour),0)/nullif(coalesce(sum(cowork_value_per_hour),0),0) ratio from native_paired_shadow_trials where status='completed'),x as(select *,nw::float8/nullif(n,0) p from s) select n,nw,cw,coalesce(p,0),case when n=0 then 0 else ((p+1.9208/n)-1.96*sqrt((p*(1-p)+0.9604/n)/n))/(1+3.8416/n) end,ratio,n>=p_min_pairs and ratio>=500 and (((p+1.9208/n)-1.96*sqrt((p*(1-p)+0.9604/n)/n))/(1+3.8416/n))>=0.5 from x $$;
grant execute on function native_promotion_evidence(int) to service_role;
