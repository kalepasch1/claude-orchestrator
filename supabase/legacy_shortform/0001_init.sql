-- Claude Orchestrator Cloud - schema
-- Apply with: supabase db push   (or paste into the Supabase SQL editor)
-- Realtime + RLS enabled. The Mac runner uses the SERVICE ROLE key (bypasses RLS);
-- the web app uses the ANON key with the policies below.

create extension if not exists vector;        -- pgvector for semantic knowledge reuse
create extension if not exists pgcrypto;

-- ---------- projects ----------
create table if not exists projects (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,
  repo_path   text not null,                  -- absolute path on the runner machine
  default_base text not null default 'main',
  created_at  timestamptz not null default now()
);

-- ---------- tasks (the work queue) ----------
create type task_state as enum
  ('QUEUED','WAITING','RUNNING','RETRY','DONE','BLOCKED','CONFLICT','TESTFAIL','MERGED');

create table if not exists tasks (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid references projects(id) on delete cascade,
  slug        text not null,
  prompt      text not null,
  base_branch text not null default 'main',
  model       text,                            -- null => router decides
  deps        text[] not null default '{}',    -- slugs that must finish first
  kind        text not null default 'build',   -- build | research | efficiency | self
  state       task_state not null default 'QUEUED',
  attempt     int not null default 0,
  account     text,
  note        text,
  log_tail    text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists tasks_state_idx on tasks(state);

-- ---------- approvals (material changes + proposals, with chat-style rationale) ----------
create type approval_status as enum ('pending','approved','denied');

create table if not exists approvals (
  id            uuid primary key default gen_random_uuid(),
  project       text,
  slug          text,
  kind          text not null default 'material',   -- material | proposal | efficiency | self | secret
  title         text not null,
  why           text,
  value         text,
  risk          text,
  alternatives  jsonb not null default '[]',
  command       text,
  detail        text,
  status        approval_status not null default 'pending',
  created_at    timestamptz not null default now(),
  decided_at    timestamptz,
  decided_by    text
);
create index if not exists approvals_status_idx on approvals(status);

-- ---------- outcomes (telemetry that powers the bandit + self-improvement loop) ----------
create table if not exists outcomes (
  id            bigint generated always as identity primary key,
  task_id       uuid references tasks(id) on delete set null,
  project       text, slug text, kind text,
  model         text, account text,
  attempts      int, rate_limited boolean default false,
  tests_passed  boolean,
  input_tokens  bigint default 0, output_tokens bigint default 0,
  usd           numeric(12,4) default 0,
  wall_ms       bigint default 0,
  integrated    boolean default false,
  created_at    timestamptz not null default now()
);
create index if not exists outcomes_proj_idx on outcomes(project, model);

-- ---------- accounts (for auto-switch on exhaustion) ----------
create table if not exists accounts (
  name           text primary key,
  type           text not null default 'login',   -- login | api
  config_dir     text,
  api_key_env    text,
  priority       int not null default 100,
  cooldown_until timestamptz
);

-- ---------- runner heartbeats (is the engine alive?) ----------
create table if not exists runner_heartbeats (
  runner_id    text primary key,
  hostname     text,
  active_tasks int default 0,
  last_seen    timestamptz not null default now()
);

-- ---------- knowledge (cross-project reuse; pgvector semantic search) ----------
create table if not exists knowledge (
  id         uuid primary key default gen_random_uuid(),
  project    text,
  title      text not null,
  tags       text[] not null default '{}',
  body       text not null,
  keywords   text[] not null default '{}',
  embedding  vector(1536),                     -- nullable; falls back to keyword search
  created_at timestamptz not null default now()
);
create index if not exists knowledge_embed_idx on knowledge
  using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- semantic search RPC (used by the runner's knowledge inject step)
create or replace function match_knowledge(query_embedding vector(1536), match_count int default 3)
returns setof knowledge language sql stable as $$
  select * from knowledge
  where embedding is not null
  order by embedding <=> query_embedding
  limit match_count;
$$;

-- ---------- realtime ----------
alter publication supabase_realtime add table tasks;
alter publication supabase_realtime add table approvals;
alter publication supabase_realtime add table runner_heartbeats;

-- ---------- RLS (authenticated team members can read/act; runner uses service role) ----------
alter table projects enable row level security;
alter table tasks enable row level security;
alter table approvals enable row level security;
alter table outcomes enable row level security;
alter table runner_heartbeats enable row level security;
alter table knowledge enable row level security;

do $$
declare t text;
begin
  foreach t in array array['projects','tasks','approvals','outcomes','runner_heartbeats','knowledge']
  loop
    execute format('drop policy if exists %I_auth_read on %I;', t, t);
    execute format('create policy %I_auth_read on %I for select to authenticated using (true);', t, t);
  end loop;
  -- members may insert tasks and decide approvals from the web app
  execute 'drop policy if exists tasks_auth_write on tasks;';
  execute 'create policy tasks_auth_write on tasks for insert to authenticated with check (true);';
  execute 'drop policy if exists approvals_auth_decide on approvals;';
  execute 'create policy approvals_auth_decide on approvals for update to authenticated using (true) with check (true);';
end $$;
