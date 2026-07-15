
alter table tasks add column if not exists capability_slug text;
alter table capability_evals add column if not exists updated_at timestamptz not null default now();

do $$ declare t text; begin
  foreach t in array array['capability_instances'] loop
    execute format('drop policy if exists %I_insert on %I;', t, t);
    execute format(
      'create policy %I_insert on %I for insert to authenticated with check (true);',
      t, t
    );
  end loop;
end $$;

drop policy if exists capability_evals_update on capability_evals;
create policy capability_evals_update on capability_evals
  for update to authenticated using (true);
;
