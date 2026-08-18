# `shared/`

Cross-component contracts. Currently one file: `contracts/filings-as-code.ts`.

There is **no build here.** Nothing compiles `shared/`, nothing bundles it, and
no package resolves it. It is read as a source of truth by humans and agents, not
imported at runtime. Do not add a `.ts` file expecting it to be type-checked.

## Where do migrations for these contracts go?

Not here. There is no `shared/db_migrations/`, and one should not be created.

A schema change that accompanies a contract change belongs in the migration home
that already exists:

| Home | What lives there |
|---|---|
| `supabase/migrations/` | Platform schema — the tables these contracts describe. **Default.** |
| `runner/migrations/` | RPCs and functions the runner installs. |
| `web/supabase/migrations/` | The web app's own tree. |

Scaffold one rather than hand-rolling the filename:

```bash
python3 runner/new_migration.py "add filing status column" \
  --summary "filings-as-code contract gains a status field"
```

That writes `supabase/migrations/<YYYYMMDDHHMMSS>_add_filing_status_column.sql`
with an idempotent skeleton. `--dry-run` prints the path and body without
writing; `--home runner/migrations` targets another canonical home. Any other
directory is refused on purpose — see `runner/new_migration.py` for why, and
`runner/tests/test_new_migration.py` for the tests that keep it that way.

Migrations must be idempotent: `runner/apply_sql_migrations.py` may apply the
same file more than once.

## History

A queued task once asked for an empty `shared/db_migrations/migration.ts` as a
"template for future migration scripts". It was refused — an empty placeholder
enforces nothing, and a TypeScript migration home would have been a fourth
convention competing with the three above. This file plus
`runner/new_migration.py` are the replacement: the same question, answered with
something executable.
