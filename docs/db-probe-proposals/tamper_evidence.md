# Probe proposal: `forge_records_tamper_evidence`

**Status: FILLED (2026-09-15) by `record_tables_tamper_evidence`** — the probe forge's first fill.

The scaffold below is what `db_probe_forge.spec_for("records_integrity_and_audit_trail", "tamper_evidence")`
generated; the placeholder id `forge_records_tamper_evidence` became the catalog-conventional
`record_tables_tamper_evidence` (ids name the object and the measurement, like
`updated_at_without_trigger`), and the forge's `availability` default became the `audit` category.

| | |
|---|---|
| Probe id | `record_tables_tamper_evidence` (`runner/db_probes.py`: `_p_tamper_evidence`, `_SQL[...]`, `PROBES`) |
| Tier / category / evidence | `cheap` / `audit` / `audit_trail` — PostgreSQL only |
| Memo argument | `records_integrity_and_audit_trail.tamper_evidence`: "Material records are append-only or otherwise tamper-evident." |
| Tests | `runner/tests/test_db_probes.py`: `test_record_tables_tamper_evidence_severities_follow_exposure`, `test_record_tables_tamper_evidence_positives_and_tolerance`, `test_tamper_evidence_sql_measures_catalogs_and_settings_only`, plus the `NEW_PROBE_GATES` row (catalog fields, read-only, bounded, batchable, runs under `run_all`) |

## What it measures (one WITH statement, catalogs and readable settings only)

Per public table, from `pg_trigger` / `pg_proc` / `information_schema.role_table_grants` / `pg_roles`:

* **guard triggers** — enabled, non-internal triggers on UPDATE or DELETE (`tgtype & 24`) whose function
  is named like `*audit*`, `*immutable*`, `*no_update*`, `*prevent*`, ... (`GUARD_FUNC_PATTERN`) or whose
  body RAISEs;
* **stamp triggers** — UPDATE triggers whose function is named like `moddatetime` / `set_updated_at` / ...
  (`STAMP_FUNC_PATTERN`);
* **non-owner rewriters** — grantees of UPDATE/DELETE other than the table owner and the platform roles,
  split into *unconditional* (RLS off on the table, or the role has `rolbypassrls`) and *policy-gated*;
  plus TRUNCATE grantees (TRUNCATE is never policy-gated);
* **change-log posture** — `pg_settings` rows for `wal_level`, `archive_mode`, `track_commit_timestamp`,
  `log_statement`, `pgaudit.log` (`TAMPER_SETTINGS`), unioned into the same result as `kind = 'setting'`.

Record-ness is decided in Python by name (`AUDIT_TABLE_PATTERN`: `*_events`, `*_log`, `*audit*`,
`*_history`, `*_ledger`, `*_trail`, `*_journal`). Never a row value; `ORDER BY kind, schemaname,
tablename, setting_name LIMIT 500`; passes `assert_read_only`.

## Severities (justified by what was measured)

| Finding | Severity | Direction |
|---|---|---|
| Record table, no guard trigger, UPDATE/DELETE granted to a non-owner role that no policy gates (RLS off, or `rolbypassrls`) | `high` | undermines |
| Record table, no guard, UPDATE/DELETE granted but RLS on and policies decide | `medium` | undermines |
| Record table, no guard, only a TRUNCATE grant to a non-owner role | `medium` | undermines |
| Record table, no guard, only the owner can rewrite it | `low` | undermines |
| Every record table carries a guard (`extra=all_guarded`) | `info` | supports |
| N of M mutable tables rewritable by non-owner roles with no audit or stamp trigger (`extra=mutable_tracing`) | `low` | undermines |
| Every mutable table traced or owner-only (`extra=mutable_tracing`) | `info` | supports |
| Change-log posture (`extra=change_log_posture`): supports when `track_commit_timestamp`, `log_statement` in (mod, all), `archive_mode` or `pgaudit.log` records changes; undermines otherwise | `info` | either |

Facts written for the posture snapshot: `record_tables`, `record_tables_unguarded`.

## Live validation

Run read-only against the fleet control plane on 2026-09-15 (direct and through the batch wrapper):
480 rows (5 settings + 475 public tables), 31 record tables, none guarded, `run_probe` ok. Every
record table is rewritable by `service_role` (bypasses RLS), which is precisely the gap the memo
argument names.

---

## Original scaffold (as generated)

_Demand-driven: memo argument `tamper_evidence` of `records_integrity_and_audit_trail` has zero evidence coverage._

Claim to measure: Material records are append-only or otherwise tamper-evident.

## Sketch

```sql
-- TODO(host-model): the read-only statement that measures:
--   Material records are append-only or otherwise tamper-evident.
-- Constraints: SELECT against catalogs only; no row values; limit 500; deterministic ordering; assert_read_only enforced by the adapter.
```

## Parser contract

rows -> [make_finding('forge_records_tamper_evidence', ...)] ; severity from metrics; supports-direction info row is encouraged when the invariant holds

## Fixture test

test_db_probes.py: run_parse('forge_records_tamper_evidence', rows) pins titles/severities/metrics

## Registration (db_probes.PROBES)

`_probe("forge_records_tamper_evidence", "Covers memo argument tamper_evidence of records_integrity_and_audit_trail", "availability", "cheap", ('audit_trail', 'integrity'), <parser>, "<remediation>")`

## Safety

read-only; no PII values; caps like ORCH_DB_PROBE_MAX_ROWS apply

---
Generated by db_probe_forge (deterministic scaffold; fill SQL parser TODOs on a host model pass).
