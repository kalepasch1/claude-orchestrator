-- bidirectional learning: worker agents report how the ORCHESTRATION could improve
create table if not exists orchestrator_feedback (
  id uuid primary key default gen_random_uuid(),
  task_id uuid, project text, slug text, source text default 'agent',
  category text not null default 'other',  -- context|model|prompt|tooling|guardrail|strategy|rate_limit|other
  severity text not null default 'med',    -- low|med|high
  observation text not null, suggestion text, evidence text,
  status text not null default 'new',      -- new|triaged|applied|dismissed
  created_at timestamptz not null default now()
);
create index if not exists feedback_status_idx on orchestrator_feedback(status, category);
alter table orchestrator_feedback enable row level security;
do $$ begin
  execute 'drop policy if exists ofb_read on orchestrator_feedback';
  execute 'create policy ofb_read on orchestrator_feedback for select to authenticated using (true)';
  execute 'drop policy if exists ofb_write on orchestrator_feedback';
  execute 'create policy ofb_write on orchestrator_feedback for insert to authenticated with check (true)';
end $$;
alter publication supabase_realtime add table orchestrator_feedback;;
