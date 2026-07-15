-- one-click reviewer actions raised from the console; the runner drains + fulfills them
create table if not exists determination_actions (
  id uuid primary key default gen_random_uuid(),
  determination_id uuid, action text,          -- replay | ask | approve | override | another-round
  payload jsonb, status text default 'pending', -- pending | done | error
  result jsonb, reviewer text, created_at timestamptz default now(), done_at timestamptz
);
create index if not exists idx_detact_status on determination_actions(status);

-- live streaming deliberation: experts posting / debating / converging, in order
create table if not exists deliberation_events (
  id uuid primary key default gen_random_uuid(),
  subject_id uuid, seq integer, kind text,      -- assemble | opening | debate | synthesis | done
  expert text, verdict text, text text, created_at timestamptz default now()
);
create index if not exists idx_delibev on deliberation_events(subject_id, seq);

-- store the issue body so a determination can be re-run (replay)
alter table determinations add column if not exists body text;
alter table committee_scoreboard add column if not exists brier numeric;;
