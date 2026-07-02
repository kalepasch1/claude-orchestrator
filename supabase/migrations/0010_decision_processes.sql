-- v3.9: decision_processes table for founder directives with auto-generated artifacts
-- when a founder chooses "negotiate" or "file", the decision_engine generates a draft
-- (counter-email, term sheet, filing memo, etc.) and attaches it here for review + send.

create type directive_type as enum
  ('negotiate', 'file', 'draft', 'review', 'approve', 'deny', 'escalate');

create table if not exists decision_processes (
  id uuid primary key default gen_random_uuid(),
  project text not null,
  approval_id uuid,                              -- reference to approvals table
  title text not null,                           -- e.g., "Counter-offer negotiation"
  directive directive_type not null,             -- what the founder chose
  context jsonb not null default '{}',           -- full decision context (parties, terms, etc.)
  draft text,                                    -- auto-generated artifact (email, memo, filing, etc.)
  draft_model text,                              -- which model generated the draft
  draft_tokens_in bigint default 0, draft_tokens_out bigint default 0,
  draft_cost_usd numeric(10,4) default 0,
  status text not null default 'draft',          -- draft | reviewed | sent | completed | failed
  reviewed_at timestamptz,
  reviewed_by text,
  sent_at timestamptz,
  completed_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists decision_processes_project_idx on decision_processes(project, status);
create index if not exists decision_processes_approval_idx on decision_processes(approval_id);

alter table decision_processes enable row level security;

do $$ begin
  execute 'drop policy if exists decision_processes_read on decision_processes';
  execute 'create policy decision_processes_read on decision_processes for select to authenticated using (true)';
  execute 'drop policy if exists decision_processes_write on decision_processes';
  execute 'create policy decision_processes_write on decision_processes for insert to authenticated with check (true)';
  execute 'drop policy if exists decision_processes_update on decision_processes';
  execute 'create policy decision_processes_update on decision_processes for update to authenticated using (true) with check (true)';
end $$;

alter publication supabase_realtime add table decision_processes;
