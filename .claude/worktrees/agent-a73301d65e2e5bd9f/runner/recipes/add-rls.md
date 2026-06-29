# Recipe: add Supabase Row Level Security to a table

Add RLS to the `{{table}}` table in this repo's Supabase schema.

Steps:
1. Create a migration file (NEVER run raw SQL in the shell) that:
   - `alter table {{table}} enable row level security;`
   - adds explicit policies: authenticated users select their own rows; service_role full.
   - wrap policy creation so re-running is idempotent (drop policy if exists first).
2. Default-DENY: no permissive `using (true)` for writes unless intentional and reviewed.
3. Apply via the migration tool, then run `get_advisors` to confirm no RLS warnings remain.
4. Add/adjust a test that an anon client cannot read/write rows it shouldn't.

Acceptance: advisors show no RLS-disabled/over-permissive warning for `{{table}}`; tests pass.
