# orch-rescue reconciliation — fingerprint 764fd6ce53c9 (session-fabric cluster)

Verdict for the four rescue sweeps that share the 15–18 file working set. Base:
`origin/master@59b85efe`. Newest sweep semantically diffed per file:
`refs/orch-rescue/20260813T034449-orchestrator-session-fabric-current-7ba40cac`.

**Bottom line: the sweep is an older divergent lineage, NOT stale-and-equal. Master
solved the same area differently and, in 17 of 18 files, more completely. Exactly one
behaviour in the sweep is genuinely absent from master, and it is a security defect —
that one item is recovered here. The sweep is not bulk-applied, and no
`refs/orch-rescue/*` ref was deleted or rewritten.**

## The one RECOVERABLE_VALUE item

`runner/release_train.py::_insert_release` on master reads:

```python
try:
    return db.insert("releases", dict(row, host=paused_host_guard.HOST))
except Exception:
    return db.insert("releases", row)
```

The docstring says this retries "if the column is not present yet". The code retries on
*any* exception. The DB fence installed by `20260811160000_paused_host_release_guard_v2.sql`
fires `when (NEW.host is not null and NEW.host <> '')`. So when the guard refuses a
paused host's write, the blanket `except` immediately re-submits **the identical row with
`host` stripped**, the trigger's WHEN clause does not match, and the row lands
anonymously. The retry path walks straight through the fence that had just refused it —
defeating the single reason the `host` column was added.

It was also silent: the v2 migration's own comment states that the trigger cannot record
its refusal (the in-trigger `insert`/`pg_notify` roll back with the `RAISE`), so the
durable record is the caller's job. Master's caller never made that call.

Recovered patch, minimal:
- narrow the `except` to the genuinely-absent-column case only; re-raise everything else;
- call `paused_host_guard.record_rejection("release_insert", …)` on a guard refusal;
- correct the docstring, which promised the narrow behaviour the code did not implement.

Regression cover added to `runner/tests/test_paused_host_scope.py`:
- `test_release_insert_never_strips_host_after_guard_rejection` — exactly one insert
  attempt, `host` present on it, refusal recorded;
- `test_an_unrelated_db_error_is_not_swallowed_by_the_compat_retry` — a deadlock does not
  earn a second, anonymous attempt.

`runner/tests/test_paused_host_scope.py`: 31 passed. Scope
`-k "release_train or paused_host or release"`: 41 failed / 328 passed before, 41 failed /
330 passed after — the same 41 pre-existing failures
(`test_relfix_pareto_2080_release_conflict_healing.py`, `test_release_on_capacity.py`
collection errors), unrelated to this change.

## Migration timestamp — reported, not a live hazard

`supabase/migrations/20260811160000_paused_host_release_guard_v2.sql` exists on **both**
master and the sweep with **different file bodies** at the **same timestamp**. Contents
were compared line by line:

- The SQL objects are equivalent — same `alter table … add column if not exists host`,
  same `create or replace function public.enforce_paused_host_release_guard()`, same
  `drop trigger if exists` + `create trigger … before insert … when (NEW.host is not null
  and NEW.host <> '')`, same `check_violation` errcode.
- Master's copy (96 lines) is a strict documentation superset of the sweep's (50 lines):
  it carries the v1-bug postmortem, the recovery provenance, and the rationale for
  INSERT-only / NULL-host-passes / shared `stale_host_is_paused()`.

So master already absorbed this migration's behaviour and the divergence is prose only.
The hazard worth recording is procedural rather than schematic: **two different file
bodies have existed under one migration filename**, so any environment that applied the
sweep's copy holds a different checksum for `20260811160000` than master's. Migration
runners that verify checksums will flag it. Resolution is to treat master's copy as
canonical (it is the superset) and re-baseline the checksum where the sweep's copy was
applied — not to add a new migration, since the objects already match.

## Per-file verdict — master ahead, nothing to recover (17 files)

| File | Why master wins |
|---|---|
| `runner/release_train.py` | Master adds `delivery_lease.require()` release fencing (2026-08-13) and the whole-tree `resolved_file_gate` (2026-08-12). Neither exists in the sweep. Only `_insert_release`'s except clause was behind — recovered above. |
| `runner/tests/test_paused_host_scope.py` | Master's `PausedHostReleaseGuardV2MigrationTests` is a superset of the sweep's `TestMigrationV2TransactionTruth`, and asserts on raw (not lowercased) SQL. Only the missing `_insert_release` case was recovered. |
| `web/server/utils/fleetHealth.ts` | Different architecture, not a regression: master reads a sentinel state file via `fleetHealthPaths()`; the sweep summarizes a `runner_heartbeats` ledger. Master's is the shipped design and the one `fleetHealth.test.ts` on master targets. Adopting the sweep would be a redesign, out of scope for a recovery task. |
| `web/types/fleet-health.ts` | The sweep's extra fields (`status`, `heartbeat_seconds`, `machines_live`, `contract_consistent`) belong to the ledger design above; dead types without it. |
| `web/server/api/fleet-health.get.ts`, `web/composables/useFleetHealth.ts`, `web/components/FleetHealthBadge.vue` | Consumers of the same superseded ledger design. |
| `web/server/api/terminal/execute.post.ts`, `web/components/DevelopmentTerminal.vue` | Master's versions are later; the sweep's 112-line delta is the pre-refactor shape. |
| `web/components/ProofTimeline.vue`, `web/pages/index.vue`, `web/pages/orchestrators/[slug].vue`, `web/composables/useOrchestratorSnapshot.ts`, `web/server/api/orchestrator/snapshot.get.ts` | Presentation deltas against master's later refactor; no behaviour master lacks. |
| `web/server/utils/fleetHealth.test.ts`, `web/server/utils/releaseSurface.test.ts`, `web/vitest.config.ts` | Test/config deltas that only make sense paired with the superseded ledger design. |

The three older sweeps (`364b3d7a`, `a05140c3`, `15d8c552`) are subsets of `7ba40cac`
over the same paths and were checked to add nothing beyond it.

Reproduce the classification with:

```
python3 runner/tools/reconcile_orch_rescue.py --repo . --base origin/master
```
