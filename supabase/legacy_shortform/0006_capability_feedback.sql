-- v3.5: federated capability feedback loop
-- adds capability_slug to tasks so runner can tag which capability a task used;
-- adds updated_at to capability_evals for last-pass tracking;
-- adds insert/update policies so the edge function can write evals.

alter table tasks add column if not exists capability_slug text;
alter table capability_evals add column if not exists updated_at timestamptz not null default now();

-- allow authenticated users (dashboard) to trigger go-to-market inserts
do $$ declare t text; begin
  foreach t in array array['capability_instances'] loop
    execute format('drop policy if exists %I_insert on %I;', t, t);
    execute format(
      'create policy %I_insert on %I for insert to authenticated with check (true);',
      t, t
    );
  end loop;
end $$;

-- allow authenticated users to update capability_evals.last_pass via dashboard/edge fn
drop policy if exists capability_evals_update on capability_evals;
create policy capability_evals_update on capability_evals
  for update to authenticated using (true);
