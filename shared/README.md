# `shared/`

Cross-component contracts: the **shared vocabulary** for the fleet — the type and
interface definitions that sibling work items agree on before any of them writes
an actuator.

Its purpose is coordination, not behaviour. When several tasks in a batch touch
the same concept — a filing, a lane, a verdict — each one otherwise invents its
own shape for it, and the shapes drift apart the moment they are implemented in
parallel. Defining the shape once, here, gives every sibling a single definition
to reason against.

There is **no build here.** Nothing compiles `shared/`, nothing bundles it, and
no package resolves it. It is read as a source of truth by humans and agents, not
imported at runtime. Do not add a `.ts` file expecting it to be type-checked.

## Stubs only — no implementation is included

**The contents of this directory are stubs.** Nothing here executes fleet work:
it does not kill a process, write a row, schedule a daemon, call a network
service, or read the database. A contract file may carry small pure helpers so
the type is usable (date arithmetic, predicates, constructors), but the behaviour
those types describe lives in the sibling modules — never in `shared/`.

Consequences worth stating plainly:

- Importing from `shared/` must never have a side effect.
- A change here is a change to an interface that other tasks are already building
  against, so it is a breaking change until every sibling is updated.
- Absence of a contract file is not permission to invent one inline; add it here
  first.

## Where the contract definitions live

Contract definitions live under `shared/contracts/`. Files expected to be present
(listed by location and subject only — see each file for its own definitions):

| Path | Subject |
|---|---|
| `shared/contracts/filings-as-code.ts` | Regulatory filing specs, cadences, due-date rolls, filing status, accountable officers, assessments, and regulator feed records |

Related contract vocabularies documented elsewhere in the repo, for orientation:

- `runner/FLEET_IMMUNE_CONTRACTS.md` — fleet immune-system contracts (lanes,
  daemons, capacity, host liveness, release gate, route quality) and the three
  invariants siblings must honour.

## Conventions

- One subject per file; name the file after the subject, in `kebab-case.ts`.
- Export types and interfaces; keep any helper pure, total, and fail-soft.
- Do not import from `runner/`, `server/`, `web/` or `src/` — contracts sit below
  them.
- Add the file to the table above in the same change that introduces it.

Sibling tasks implement against these contracts.

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
