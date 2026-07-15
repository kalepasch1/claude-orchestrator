-- auto-experiments: A/B a feedback-suggested orchestrator change before adopting it
create table if not exists experiments (
  id uuid primary key default gen_random_uuid(),
  category text, knob text,
  current_value text, candidate_value text,
  current_score numeric(4,3), candidate_score numeric(4,3),
  current_cost numeric(12,4), candidate_cost numeric(12,4),
  verdict text,                          -- adopt | reject | inconclusive | no_evals
  detail text, created_at timestamptz not null default now()
);
alter table experiments enable row level security;
do $$ begin
  execute 'drop policy if exists exp_read on experiments';
  execute 'create policy exp_read on experiments for select to authenticated using (true)';
end $$;
alter publication supabase_realtime add table experiments;;
