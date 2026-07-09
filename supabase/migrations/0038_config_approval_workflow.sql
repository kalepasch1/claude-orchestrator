-- 0038_config_approval_workflow.sql — approval gating for fleet_config changes.
-- A requester proposes (key, value) via config_requests; an allow-listed approver
-- in fleet_approvers accepts or rejects it before the value reaches fleet_config.
-- Service role (runner/plane) bypasses RLS; dashboard + bridge use authenticated
-- policies below.

-- ---------- config_requests: one row per proposed config change ----------
create table if not exists config_requests (
  id          uuid primary key default gen_random_uuid(),
  key         text not null,
  value       text not null,
  requester   text not null,
  status      text not null default 'pending'
                check (status in ('pending', 'approved', 'rejected')),
  created_at  timestamptz not null default now()
);

alter table config_requests add column if not exists key        text;
alter table config_requests add column if not exists value      text;
alter table config_requests add column if not exists requester  text;
alter table config_requests add column if not exists status     text not null default 'pending';
alter table config_requests add column if not exists created_at timestamptz not null default now();

create index if not exists config_requests_status_idx     on config_requests(status, created_at desc);
create index if not exists config_requests_requester_idx  on config_requests(requester, created_at desc);

-- ---------- config_approvals: decision records (append-only) ----------
create table if not exists config_approvals (
  id          uuid primary key default gen_random_uuid(),
  request_id  uuid not null references config_requests(id) on delete cascade,
  approver    text not null,
  decision    text not null check (decision in ('approved', 'rejected')),
  reason      text,
  decided_at  timestamptz not null default now()
);

alter table config_approvals add column if not exists request_id uuid;
alter table config_approvals add column if not exists approver   text;
alter table config_approvals add column if not exists decision   text;
alter table config_approvals add column if not exists reason     text;
alter table config_approvals add column if not exists decided_at timestamptz not null default now();

create index if not exists config_approvals_request_idx on config_approvals(request_id, decided_at desc);

-- ---------- RLS ----------
alter table config_requests  enable row level security;
alter table config_approvals enable row level security;

do $$ begin
  -- Requesters see their own requests; fleet_approvers see all.
  execute 'drop policy if exists config_requests_read on config_requests';
  execute $p$create policy config_requests_read on config_requests
    for select to authenticated
    using (
      requester = auth.jwt()->>'email'
      or exists (
        select 1 from fleet_approvers a where a.email = auth.jwt()->>'email'
      )
    )$p$;

  -- Any authenticated user may open a request; they must self-declare as requester.
  execute 'drop policy if exists config_requests_create on config_requests';
  execute $p$create policy config_requests_create on config_requests
    for insert to authenticated
    with check (requester = auth.jwt()->>'email')$p$;

  -- Only an allow-listed approver may flip the status.
  execute 'drop policy if exists config_requests_decide on config_requests';
  execute $p$create policy config_requests_decide on config_requests
    for update to authenticated
    using    (exists (select 1 from fleet_approvers a where a.email = auth.jwt()->>'email'))
    with check (exists (select 1 from fleet_approvers a where a.email = auth.jwt()->>'email'))$p$;

  -- Requesters see approvals on their own requests; approvers see all.
  execute 'drop policy if exists config_approvals_read on config_approvals';
  execute $p$create policy config_approvals_read on config_approvals
    for select to authenticated
    using (
      exists (
        select 1 from config_requests r
        where  r.id = request_id
          and  (
            r.requester = auth.jwt()->>'email'
            or exists (select 1 from fleet_approvers a where a.email = auth.jwt()->>'email')
          )
      )
    )$p$;

  -- Only approvers may record a decision.
  execute 'drop policy if exists config_approvals_insert on config_approvals';
  execute $p$create policy config_approvals_insert on config_approvals
    for insert to authenticated
    with check (
      approver = auth.jwt()->>'email'
      and exists (select 1 from fleet_approvers a where a.email = auth.jwt()->>'email')
    )$p$;
end $$;

-- ---------- realtime ----------
do $$ begin
  begin execute 'alter publication supabase_realtime add table config_requests';  exception when others then null; end;
  begin execute 'alter publication supabase_realtime add table config_approvals'; exception when others then null; end;
end $$;

select '0038_config_approval_workflow OK – tables: config_requests, config_approvals' as status;
