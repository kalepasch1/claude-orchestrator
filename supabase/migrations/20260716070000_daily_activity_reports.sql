-- Durable morning review artifact. Pending decisions stay in approvals/v_action_inbox;
-- this table records what happened and points the owner back to that single queue.
create table if not exists public.daily_activity_reports (
  id uuid primary key default gen_random_uuid(),
  report_date date not null unique,
  window_start timestamptz not null,
  window_end timestamptz not null,
  report jsonb not null default '{}'::jsonb,
  markdown text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists daily_activity_reports_date_idx on public.daily_activity_reports(report_date desc);
alter table public.daily_activity_reports enable row level security;
drop policy if exists daily_activity_reports_read on public.daily_activity_reports;
create policy daily_activity_reports_read on public.daily_activity_reports for select to authenticated using (true);
do $$ begin
  begin execute 'alter publication supabase_realtime add table public.daily_activity_reports'; exception when others then null; end;
end $$;
