-- rich, non-binary decision support on top of approvals
alter table approvals add column if not exists brief_json jsonb;      -- structured options/tradeoffs/recommendation
alter table approvals add column if not exists decision_type text;    -- approve|deny|conditions|negotiate|directive|more_info
alter table approvals add column if not exists decision_text text;    -- your free-text answer / conditions / directive
alter table approvals add column if not exists process_spawned boolean default false;
alter table approvals add column if not exists brief_status text;     -- null|generating|ready

-- threaded back-and-forth on a decision (you ask, the engine answers with analysis)
create table if not exists decision_messages (
  id uuid primary key default gen_random_uuid(),
  approval_id uuid not null,
  role text not null,                    -- owner | assistant
  body text,
  created_at timestamptz default now()
);
create index if not exists idx_decmsg_appr on decision_messages(approval_id, created_at);

-- a decision that implies action can spawn a process instantly
create table if not exists decision_processes (
  id uuid primary key default gen_random_uuid(),
  approval_id uuid, project text, directive text,
  status text default 'queued',          -- queued|planning|running|done
  spawned_task_ids uuid[], created_at timestamptz default now()
);;
