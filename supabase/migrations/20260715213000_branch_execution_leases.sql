-- One writer per project branch across every Mac and executor surface.
-- Worktrees isolate directories; this lease isolates the mutable git ref.
create table if not exists public.branch_execution_leases (
  project_id uuid not null references public.projects(id) on delete cascade,
  branch text not null,
  task_id uuid not null references public.tasks(id) on delete cascade,
  owner text not null,
  token uuid not null,
  base_sha text,
  remote_sha text,
  acquired_at timestamptz not null default now(),
  heartbeat_at timestamptz not null default now(),
  expires_at timestamptz not null,
  released_at timestamptz,
  primary key (project_id, branch)
);
create index if not exists branch_execution_leases_task_idx
  on public.branch_execution_leases(task_id);
create index if not exists branch_execution_leases_expiry_idx
  on public.branch_execution_leases(expires_at)
  where released_at is null;
alter table public.branch_execution_leases enable row level security;
create or replace function public.acquire_branch_execution_lease(
  p_project_id uuid,
  p_branch text,
  p_task_id uuid,
  p_owner text,
  p_token uuid,
  p_base_sha text default null,
  p_remote_sha text default null,
  p_ttl_seconds integer default 3600
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  current_lease public.branch_execution_leases%rowtype;
begin
  if p_branch is null or btrim(p_branch) = '' or p_ttl_seconds < 60 then
    return false;
  end if;

  -- Serialize contenders even when the row does not exist yet.
  perform pg_advisory_xact_lock(hashtextextended(p_project_id::text || ':' || p_branch, 0));
  select * into current_lease
    from public.branch_execution_leases
   where project_id = p_project_id and branch = p_branch
   for update;

  if not found then
    insert into public.branch_execution_leases
      (project_id, branch, task_id, owner, token, base_sha, remote_sha, expires_at)
    values
      (p_project_id, p_branch, p_task_id, p_owner, p_token, p_base_sha, p_remote_sha,
       now() + make_interval(secs => p_ttl_seconds));
    return true;
  end if;

  if (current_lease.task_id = p_task_id and current_lease.token = p_token)
     or current_lease.released_at is not null
     or current_lease.expires_at <= now() then
    update public.branch_execution_leases
       set task_id = p_task_id,
           owner = p_owner,
           token = p_token,
           base_sha = p_base_sha,
           remote_sha = p_remote_sha,
           acquired_at = case
             when current_lease.task_id = p_task_id and current_lease.token = p_token
               then current_lease.acquired_at
             else now()
           end,
           heartbeat_at = now(),
           expires_at = now() + make_interval(secs => p_ttl_seconds),
           released_at = null
     where project_id = p_project_id and branch = p_branch;
    return true;
  end if;

  return false;
end;
$$;
create or replace function public.heartbeat_branch_execution_lease(
  p_project_id uuid,
  p_branch text,
  p_task_id uuid,
  p_token uuid,
  p_ttl_seconds integer default 3600
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare changed integer;
begin
  update public.branch_execution_leases
     set heartbeat_at = now(),
         expires_at = now() + make_interval(secs => greatest(p_ttl_seconds, 60))
   where project_id = p_project_id
     and branch = p_branch
     and task_id = p_task_id
     and token = p_token
     and released_at is null
     and expires_at > now();
  get diagnostics changed = row_count;
  return changed = 1;
end;
$$;
create or replace function public.release_branch_execution_lease(
  p_project_id uuid,
  p_branch text,
  p_task_id uuid,
  p_token uuid
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare changed integer;
begin
  update public.branch_execution_leases
     set released_at = now(), heartbeat_at = now(), expires_at = now()
   where project_id = p_project_id
     and branch = p_branch
     and task_id = p_task_id
     and token = p_token
     and released_at is null;
  get diagnostics changed = row_count;
  return changed = 1;
end;
$$;
revoke all on public.branch_execution_leases from anon, authenticated;
grant execute on function public.acquire_branch_execution_lease(uuid,text,uuid,text,uuid,text,text,integer)
  to authenticated, service_role;
grant execute on function public.heartbeat_branch_execution_lease(uuid,text,uuid,uuid,integer)
  to authenticated, service_role;
grant execute on function public.release_branch_execution_lease(uuid,text,uuid,uuid)
  to authenticated, service_role;
