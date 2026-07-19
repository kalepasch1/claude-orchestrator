-- v3.8: add missing RLS policies so the dashboard can do the writes it needs.
-- loops: dashboard needs UPDATE (toggleLoop enable/disable, cadence tuning by meta_loop)
-- session_actions: dashboard runSession marks status='queued' via UPDATE
-- resource_events: runner INSERT (already service-role via no policy); dashboard SELECT (add policy)
-- controls: already has 'for all' policy from 0008; just ensure it exists.

do $$ begin
  -- loops: allow authenticated UPDATE (toggle enabled, health score writes from meta_loop)
  execute 'drop policy if exists loops_update on loops';
  execute 'create policy loops_update on loops for update to authenticated using (true) with check (true)';

  -- session_actions: allow authenticated INSERT (watcher) + UPDATE (dashboard marks queued)
  execute 'drop policy if exists session_actions_write on session_actions';
  execute 'create policy session_actions_write on session_actions for insert to authenticated with check (true)';
  execute 'drop policy if exists session_actions_update on session_actions';
  execute 'create policy session_actions_update on session_actions for update to authenticated using (true) with check (true)';

  -- resource_events: runner inserts via service role; dashboard reads via SELECT policy
  execute 'drop policy if exists resource_events_insert on resource_events';
  execute 'create policy resource_events_insert on resource_events for insert to authenticated with check (true)';
end $$;

-- provider_budgets: dashboard may want to set per-project budgets
do $$ begin
  execute 'drop policy if exists provider_budgets_write on provider_budgets';
  execute 'create policy provider_budgets_write on provider_budgets for insert to authenticated with check (true)';
  execute 'drop policy if exists provider_budgets_update on provider_budgets';
  execute 'create policy provider_budgets_update on provider_budgets for update to authenticated using (true) with check (true)';
end $$;;
