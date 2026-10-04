# Recipe: add Supabase Row Level Security to a table

Add RLS to the `{{table}}` table in this repo's Supabase schema.

Steps:
1. Create a migration file (NEVER run raw SQL in the shell) that:
   - `alter table {{table}} enable row level security;`
   - adds explicit policies: authenticated users select their own rows; service_role full.
   - wrap policy creation so re-running is idempotent (drop policy if exists first).
2. Default-DENY: no permissive `using (true)` for writes unless intentional and reviewed.
3. Do NOT apply it to the production database from this branch (no Supabase MCP
   `apply_migration`, no DDL through `execute_sql`, no `supabase db push` from a feature
   checkout). The orchestrator only applies migrations that are already on main: the file is
   merged to consolidation/main (the project's staging branch), promoted to main, and only then
   applied from a clean checkout of origin/main (`runner/migration_main_guard.py` refuses
   anything else). Verify the policies against a local/preview database instead.
4. Add/adjust a test that an anon client cannot read/write rows it shouldn't.

Acceptance: the migration file + test are on the branch; once it reaches main and is applied,
advisors show no RLS-disabled/over-permissive warning for `{{table}}`; tests pass.
