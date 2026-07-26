-- Create hivemind_memory table for cross-session pattern storage
create table if not exists hivemind_memory (
  id uuid primary key default gen_random_uuid(),
  project_id text not null,
  dag_id text,
  slug text not null,
  pattern_type text not null check (pattern_type in ('utility','api_shape','gotcha','architecture','type_definition','test_pattern','config_pattern')),
  summary text not null,
  content text,
  file_context text,
  tags text[] not null default '{}',
  quality_score real not null default 0.0,
  reuse_count integer not null default 0,
  last_reused_at timestamptz,
  promoted boolean not null default false,
  promoted_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_hivemind_memory_tags on hivemind_memory using gin(tags);
create index if not exists idx_hivemind_memory_project on hivemind_memory(project_id);
create index if not exists idx_hivemind_memory_quality on hivemind_memory(quality_score desc);
create index if not exists idx_hivemind_memory_reuse on hivemind_memory(reuse_count desc) where promoted = false;

alter table hivemind_memory enable row level security;
create policy if not exists "Service role full access" on hivemind_memory
  for all using (auth.role() = 'service_role');
