-- 0011_fleet_admin.sql — the Fleet Admin Control Plane.
-- Promotes the Orchestrator from a code-build control plane into the runtime ADMIN
-- control plane for the whole portfolio. Every app emits canonical AdminEvents here;
-- domain swarms propose AdminActions; the kernel gate (constitution + autonomy dial)
-- decides auto-run vs. approval; approvals feed Bear's Smarter account; every action
-- leaves a signed, hash-chained receipt.
--
-- Realtime + RLS enabled. Runner/plane uses the SERVICE ROLE key (bypasses RLS);
-- the web dashboard + the Smarter bridge use ANON/authenticated with the policies below.

-- ---------- approvers (allowlist; who may resolve a fleet approval) ----------
create table if not exists fleet_approvers (
  email        text primary key,
  display_name text,
  role         text not null default 'approver',   -- approver | admin
  added_at     timestamptz not null default now()
);
-- Seed the human-in-the-loop. Bear approves from his Smarter account.
insert into fleet_approvers (email, display_name, role) values
  ('kalepasch@gmail.com', 'Bear (Kale Pasch)', 'admin'),
  ('kale@heretomorrow.us', 'Bear (Kale Pasch)', 'admin')
on conflict (email) do nothing;

-- ---------- events (normalized "something happened" from every app) ----------
create table if not exists fleet_admin_events (
  id          text primary key,                    -- content-addressed by the emitter
  product     text not null,                       -- tomorrow | smarter | apparently | pareto | galop | hisanta | ...
  domain      text not null,                        -- users_access | billing | trust_safety | infra
  category    text not null,
  raw_category text,
  severity    int  not null default 30,
  title       text not null,
  summary     text not null default '',
  subject_id  text,
  amount_usd  numeric(14,2),
  details     jsonb not null default '{}',
  source_url  text,
  at          timestamptz not null default now(),
  ingested_at timestamptz not null default now()
);
create index if not exists fleet_events_domain_idx on fleet_admin_events(domain, at desc);
create index if not exists fleet_events_product_idx on fleet_admin_events(product, at desc);

-- ---------- actions (remediations proposed / taken) ----------
create table if not exists fleet_admin_actions (
  id             text primary key,
  event_id       text references fleet_admin_events(id) on delete set null,
  product        text not null,
  domain         text not null,
  type           text not null,
  actor          text not null,                     -- the domain swarm / agent
  subject_id     text,
  amount_usd     numeric(14,2),
  confidence     numeric(4,3) not null default 0,
  reversibility  text not null default 'reversible',-- reversible | hard_to_reverse | irreversible
  blast_radius   text not null default 'single',    -- single | small | large | fleet
  intent         text not null,
  params         jsonb not null default '{}',
  if_not_done    text,
  decision       text,                              -- allow | escalate | deny (from the gate)
  tier           text,                              -- auto | co_pilot | human
  receipt_digest text,
  executed       boolean not null default false,
  execution_ref  text,
  undo_token     text,
  error          text,
  created_at     timestamptz not null default now(),
  executed_at    timestamptz
);
create index if not exists fleet_actions_decision_idx on fleet_admin_actions(decision, created_at desc);
create index if not exists fleet_actions_exec_idx on fleet_admin_actions(executed, tier);

-- ---------- approvals (the single human queue; mirrored into Smarter) ----------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'fleet_approval_status') then
    create type fleet_approval_status as enum ('pending','approved','modified','rejected');
  end if;
end $$;

create table if not exists fleet_approvals (
  id             text primary key,                  -- == action id it gates
  action_id      text not null references fleet_admin_actions(id) on delete cascade,
  product        text not null,
  domain         text not null,
  tier           text not null,
  priority       int not null default 0,            -- impact × urgency × irreversibility
  title          text not null,
  why            text,
  value          text,
  risk           text,
  alternatives   jsonb not null default '[]',
  intent         text,
  if_not_done    text,
  amount_usd     numeric(14,2),
  source_url     text,
  receipt_digest text,
  callback_url   text not null,                     -- where Smarter POSTs the decision
  status         fleet_approval_status not null default 'pending',
  approver       text,
  note           text,
  mirrored_to_smarter boolean not null default false,
  created_at     timestamptz not null default now(),
  decided_at     timestamptz
);
create index if not exists fleet_approvals_status_idx on fleet_approvals(status, priority desc);

-- ---------- receipts (append-only, signed, hash-chained — the audit backbone) ----------
create table if not exists fleet_receipts (
  id         text primary key,
  chain      text not null,
  seq        int  not null,
  prev_hash  text,
  digest     text not null,
  signature  jsonb not null,
  action_id  text,
  decision   text,
  reason     text,
  at         timestamptz not null default now()
);
create index if not exists fleet_receipts_chain_idx on fleet_receipts(chain, seq);

-- ---------- autonomy ledger (the escalation-learning flywheel) ----------
create table if not exists fleet_autonomy_ledger (
  domain          text not null,
  action_type     text not null,
  streak          int  not null default 0,
  total           int  not null default 0,
  clean_approvals int  not null default 0,
  edits           int  not null default 0,
  rejections      int  not null default 0,
  promoted_tier   text,
  promoted_at     timestamptz,
  updated_at      timestamptz not null default now(),
  primary key (domain, action_type)
);

-- ---------- RLS ----------
alter table fleet_approvers       enable row level security;
alter table fleet_admin_events    enable row level security;
alter table fleet_admin_actions   enable row level security;
alter table fleet_approvals       enable row level security;
alter table fleet_receipts        enable row level security;
alter table fleet_autonomy_ledger enable row level security;

do $$ begin
  -- Authenticated dashboard users can READ everything.
  execute 'drop policy if exists fleet_events_read on fleet_admin_events';
  execute 'create policy fleet_events_read on fleet_admin_events for select to authenticated using (true)';
  execute 'drop policy if exists fleet_actions_read on fleet_admin_actions';
  execute 'create policy fleet_actions_read on fleet_admin_actions for select to authenticated using (true)';
  execute 'drop policy if exists fleet_approvals_read on fleet_approvals';
  execute 'create policy fleet_approvals_read on fleet_approvals for select to authenticated using (true)';
  execute 'drop policy if exists fleet_receipts_read on fleet_receipts';
  execute 'create policy fleet_receipts_read on fleet_receipts for select to authenticated using (true)';
  execute 'drop policy if exists fleet_ledger_read on fleet_autonomy_ledger';
  execute 'create policy fleet_ledger_read on fleet_autonomy_ledger for select to authenticated using (true)';
  execute 'drop policy if exists fleet_approvers_read on fleet_approvers';
  execute 'create policy fleet_approvers_read on fleet_approvers for select to authenticated using (true)';

  -- Only an allow-listed approver may resolve an approval from the dashboard.
  -- (The Smarter bridge posts via the service role, having verified the approver.)
  execute 'drop policy if exists fleet_approvals_resolve on fleet_approvals';
  execute $p$create policy fleet_approvals_resolve on fleet_approvals
    for update to authenticated
    using (exists (select 1 from fleet_approvers a where a.email = auth.jwt()->>'email'))
    with check (exists (select 1 from fleet_approvers a where a.email = auth.jwt()->>'email'))$p$;
end $$;
-- Receipts are append-only: no UPDATE/DELETE policy is ever granted (immutability).

-- ---------- realtime ----------
do $$ begin
  begin execute 'alter publication supabase_realtime add table fleet_admin_events'; exception when others then null; end;
  begin execute 'alter publication supabase_realtime add table fleet_admin_actions'; exception when others then null; end;
  begin execute 'alter publication supabase_realtime add table fleet_approvals'; exception when others then null; end;
end $$;
