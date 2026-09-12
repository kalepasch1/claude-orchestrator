# Database Steering

_Perpetual, read-only, near-zero-cost review of every linked database, turned into
steering for the coder agents, swarm-filed remediation, and evidence for internal
legal-memo drafts. Every claim below names the module that implements it._

## What it replaces, in numbers

| | Before (2026-09-11) | After (2026-09-12) |
|---|---|---|
| Databases reviewed | 8 Supabase refs typed into `security_posture` on 2026-07-02; apparently-law and illuminati missing | every Supabase project the fleet token can see (25 found, 15 active) plus any AWS / Google / other database an operator links |
| Probes per database | 1 (`COUNT(*)` of tables with RLS off) | 28 on Postgres (catalog, `pg_stat_statements`, the free Supabase security + performance advisor lints, migration drift vs. the repo) |
| Cadence | daily | cheap probes every 10 min, medium hourly, heavy daily |
| Facts per day | ~8 | ~26k probe executions, each yielding zero-to-many object-level findings; first dry run of apparently-law: 296 findings in 12 s |
| Change detection | none | a finding that appears, worsens or resolves between cycles is an event |
| Model cost of the review | none, and none possible | none: probes never call a model |
| Model cost of the intelligence | n/a | one costless-first draft per memo per **evidence change**; expert-corps gauntlet only on material changes, at most daily per memo |

Cost scales with how often the databases change, not with how often they are looked at.

## Modules

| Module | Role |
|---|---|
| `runner/db_steering_contract.py` | Shared vocabulary: providers, dialects, severities, categories, evidence kinds, memo kinds and their argument keys, `make_finding()`, `fingerprint()`, `assert_read_only()`. |
| `runner/db_registry.py` | `db_sources` registry. `discover()` enumerates Supabase projects through the Management API; `add()` links anything else by credential **reference**; `sync_security_posture()` backfills the RLS gate's list. |
| `runner/db_adapters.py` | One `query(source, sql)` across Supabase (Management API), Postgres-wire providers (psycopg / psycopg2 / `psql`), MySQL, RDS Data API, BigQuery, Snowflake. `assert_read_only()` runs before any I/O. `resolve_credential()` reads env / keychain / doppler / 1Password / file / `vault:` references and never logs a value. |
| `runner/db_probes.py` | The probe catalog (30 probes; 28 Postgres, 9 MySQL, 3 BigQuery, 2 Snowflake). Pure SQL + deterministic parse; `score()`, `summarize()`, `validate_catalog()`. |
| `runner/db_steering.py` | The loop (`loops` type `db_steering`): due tiers, fingerprint reconciliation, posture snapshots, the coder brief, swarm remediation, memo hand-off, budget and stalest-first ordering. |
| `runner/db_memo.py` | Attaches each finding to the legal-memo argument it supports or undermines, keeps `legal_memo_drafts` current, gauntlet review for material changes, `steering_signals()` for the brief. |
| `runner/db_link.py` | Operator CLI: `discover`, `add`, `test`, `scan`, `list`, `pause`, `resume`, `remove`, `brief`, `memos`, `doctor`. |
| `runner/prompt_assembler.py` | Layer `db_steering`: the per-project brief goes into every coder prompt for that project. |
| `web/…/db-steering/*`, `web/pages/admin/data-steering.vue`, `web/config/connectors.ts` (category Databases) | Dashboard: sources, posture, findings, briefs, memos; linking through Connectors. |
| `supabase/migrations/20260912000000_database_steering.sql` | `db_sources`, `db_findings`, `db_posture_snapshots`, `db_steering_briefs`, `legal_memo_drafts`, `legal_memo_evidence`. |

## How steering reaches the people and agents editing these databases

None of these channels touches a repository, a worktree, a session or an application
database. The ChatGPT/Codex sessions working on `apparently` and the worktrees under
`apparently-law-wt/` are never read or written by this subsystem.

1. **The coder brief** (`db_steering_briefs`, ≤ 2 KB per project). Built deterministically
   from open gaps (most severe first, objects named, remediation attached) plus the
   memo engine's argument-level signals. `prompt_assembler.assemble()` prepends it to
   every task in that project, so the next agent touching `matters` sees "RLS off on
   public.matters: add owner-scoped policies in the same migration" before it starts.
   Nobody is paged; the change simply arrives correct.
2. **Swarm remediation.** Material gaps (high / critical, direction `undermines`) become
   one task per (project, probe) through `swarm_enqueue` — swarm priority below every
   user-directed task, slug `swarm-db-<probe>-<project>` so a persistent gap is one
   ticket, at most `ORCH_DB_STEERING_MAX_TASKS_PER_RUN` (3) per cycle. Findings record
   the `task_slug` they were filed under. Open material findings that still carry no
   `task_slug` (first written by a manual scan, or refused by release backpressure while
   the project was RED) are re-offered on every scan until one lands; `swarm_enqueue`
   dedupes on the open intent key, so the retry is idempotent.
3. **Memo evidence.** Every finding carries `evidence_kinds`; `db_memo.attach_evidence()`
   routes it to argument keys in six internal memos (access control and least privilege;
   records integrity and audit trail; data protection posture; operational resilience;
   change control; AI use logging). Argument strength is computed from weighted supports
   vs. undermines. Prose is redrafted (costless-first) only when the memo's evidence hash
   changes; every sentence must cite a fingerprint from the ledger or the draft is
   rejected and the deterministic rendering stands. Memos are `publication_state =
   'internal'`, end with a not-legal-advice line, and never leave the control plane.

## Linking a database

Supabase needs nothing: `python3 runner/db_link.py discover` (the loop also does this
hourly). Everything else takes one command with a credential **reference**:

```bash
# AWS RDS / Aurora Postgres — password in the macOS keychain
python3 runner/db_link.py add aws_rds prod.abc.us-east-1.rds.amazonaws.com \
  --project tomorrow --label "tomorrow prod (RDS)" --region us-east-1 \
  --config database=app --config username=readonly --credential keychain:RDS_PROD_PW --test
```

```bash
# AWS through the RDS Data API (no network path needed)
python3 runner/db_link.py add aws_aurora arn:aws:rds:us-east-1:123:cluster:prod \
  --config resource_arn=arn:aws:rds:us-east-1:123:cluster:prod \
  --config secret_arn=arn:aws:secretsmanager:us-east-1:123:secret:prod-ro --config engine=postgres
```

```bash
# Google Cloud SQL through the auth proxy
python3 runner/db_link.py add gcp_cloudsql myproj:us-central1:main \
  --config host=127.0.0.1 --config port=5433 --config database=app --config username=steering \
  --credential env:CLOUDSQL_STEERING_PW --test
```

```bash
# BigQuery with a service-account JSON in 1Password
python3 runner/db_link.py add gcp_bigquery my-gcp-project --credential onepassword:op://Infra/bq-steering/credential
```

```bash
# Any Postgres / MySQL by DSN reference
python3 runner/db_link.py add postgres analytics.example.com --credential env:ANALYTICS_DSN --project smarter --test
```

Accepted reference forms: `env:NAME`, `keychain:NAME`, `doppler:PATH`,
`onepassword:op://…`, `file:/abs/path`, `vault:<connector-account-id>`. A raw DSN,
password or token is refused at the door (`db_registry.add`, the web route, and the
connectors form all enforce it), so no secret value can reach the control plane.

**From the dashboard:** Connectors → Databases → pick the provider → "Connect securely".
The credential is encrypted with `CONNECTOR_VAULT_KEY` into `connector_accounts`; the
form also registers a `db_sources` row with `credential_ref = vault:<account id>`. The
runner decrypts it with the same key (put `CONNECTOR_VAULT_KEY` in `runner/.env`).
Admin → Data steering shows sources, posture, findings, briefs and memos, and can
register a source by reference or pause / resume / remove one.

Drivers are optional and lazy: with none installed the runner falls back to the `psql` /
`mysql` / `bq` CLIs, and otherwise reports `driver missing: pip install …` for that source
without affecting any other. Supabase needs no driver at all.

## Safety and non-interference

- `assert_read_only()` rejects anything that is not a single `WITH`/`SELECT`/`SHOW`/
  `EXPLAIN` statement, any `;`, and any write/DDL shape anywhere in the text, before
  network I/O. Every adapter calls it. A false rejection costs one probe; a false
  acceptance was the failure mode designed out.
- Probes read catalogs and statistics only; the one data-touching class (orphan
  sampling) was replaced by the catalog-only `unvalidated_constraints`.
- Per-run wall-clock budget (`ORCH_DB_STEERING_BUDGET_S`, 240 s), stalest source first,
  per-source and per-probe failure isolation, three consecutive failures mark a source
  `unreachable` but keep retrying it. The memo-drafting phase that follows has its own
  budget (`ORCH_DB_STEERING_MEMO_BUDGET_S`, 300 s): a costless local model can take
  minutes per memo, so drafting defers to the next cycle rather than overlapping the
  cadence; evidence attachment, steering signals and the brief never wait on a model.
- Nothing here writes to an application database, a repo, a worktree or the intake
  queue. The only writes are control-plane tables and swarm tasks.

## Operating it

```bash
python3 runner/db_link.py doctor                                 # which optional drivers / CLIs / env keys are present
python3 runner/db_link.py list                                   # registry
python3 runner/db_link.py scan supabase:<ref> --tiers cheap,medium,heavy   # dry run, prints findings
python3 runner/db_link.py scan supabase:<ref> --write            # one real cycle for one source
python3 runner/db_steering.py                                    # one full loop cycle
python3 runner/db_link.py brief apparently-law                   # what agents are being told
python3 runner/db_link.py memos apparently-law                   # memo summary
python3 runner/db_link.py memos apparently-law --render records_integrity_and_audit_trail
```

Knobs (all `ORCH_`-prefixed, fleet-pushable): `ORCH_DB_STEERING_CADENCE_S` (600),
`ORCH_DB_STEERING_BUDGET_S` (240), `ORCH_DB_STEERING_MEMO_BUDGET_S` (300),
`ORCH_DB_STEERING_MAX_TASKS_PER_RUN` (3), `ORCH_DB_STEERING_UNFILED_RETRY_LIMIT` (200),
`ORCH_DB_STEERING_REMEDIATION` (`false` to stop filing tasks), `ORCH_DB_STEERING_BRIEF_CHARS`
(2000), `ORCH_DB_PROBE_TIMEOUT_S` (20), `ORCH_DB_PROBE_MAX_ROWS` (500),
`ORCH_DB_DISCOVERY_INTERVAL_S` (3600), `ORCH_DB_MEMO_MAX_PER_RUN` (3),
`ORCH_DB_MEMO_GAUNTLET` (`false` to skip expert review), `ORCH_DB_MEMO_GAUNTLET_MIN_INTERVAL_S`
(86400). Pause the whole loop from the Loops page (`enabled=false` on the `db_steering` row).

## Tests

`runner/tests/test_db_registry.py`, `test_db_steering.py`, `test_db_steering_wiring.py`,
`test_db_adapters.py`, `test_db_probes.py`, `test_db_memo.py`;
`web/server/utils/__tests__/dbSteering.test.ts`. None touches a network or a database.
