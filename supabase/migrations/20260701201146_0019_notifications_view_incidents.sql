-- outbound approval pushes (email/Smarter). Source of truth any surface can read.
create table if not exists notifications (
  id uuid primary key default gen_random_uuid(),
  channel text default 'email',          -- email|smarter|slack
  audience text default 'kalepasch@gmail.com',
  kind text,                              -- decision|action|alert
  title text, body text,
  approval_id uuid,
  sent boolean default false,
  created_at timestamptz default now(), sent_at timestamptz
);
create index if not exists idx_notif_unsent on notifications(created_at) where sent=false;

-- clean, stable view Smarter (or any app) reads to manage decisions from the shared Supabase
create or replace view v_pending_decisions as
select id, kind, legal_risk_level, radar_tag, coalesce(project,'-') as app,
       title, why, prebrief, draft, draft_cmd, executable, exec_status, created_at
from approvals
where status='pending'
  and (kind in ('legal','material','secret','operator')
       or title ~* 'legal|counsel|cftc|dcm|licens|regulat|securities');

-- production incidents feed for self-healing
create table if not exists incidents (
  id uuid primary key default gen_random_uuid(),
  app text, severity text default 'warn',  -- info|warn|crit
  signal text,                              -- error|uptime|latency|cost
  detail text, fixed boolean default false,
  fix_task uuid, created_at timestamptz default now()
);

-- one-command new-app requests
create table if not exists app_requests (
  id uuid primary key default gen_random_uuid(),
  name text, goal text, status text default 'requested', created_at timestamptz default now()
);;
