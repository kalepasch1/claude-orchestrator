# orch-rescue: orchestrator visibility / session fabric (fingerprint `764fd6ce53c9`)

Four rescue sweeps carry the same 15–18 file working set, every file diverging from
`origin/master` in a way that never appeared in master's history for that path —
classified `CONFLICTED_NEEDS_FOCUSED_TASK`, not stale.

| ref | files | date |
|---|---|---|
| `7ba40cac` `…20260813T034449-orchestrator-session-fabric-current` | 18 (newest) | 2026-08-13 |
| `364b3d7a` `…20260811T152527-orchestrator-session-fabric-current` | 15 | 2026-08-11 |
| `a05140c3` `…20260807T130647-orchestrator-visibility-remediation` | 15 | 2026-08-07 |
| `15d8c552` `…20260807T125256-orchestrator-visibility-remediation` | 15 | 2026-08-07 |

Semantic diff of `7ba40cac` (the newest) against master, per file. **No ref was
deleted, applied or bulk-merged**; all four remain read-only evidence.

## Conclusion

**The sweep holds behaviour master lacks — and master's not having it is a
coherent design decision, not an oversight. It should not be applied.**

That distinction is the whole finding, so the evidence for it is below rather
than asserted.

## The one file that carries new behaviour

Of 18 files, exactly one exports symbols master does not have:
`web/server/utils/fleetHealth.ts` (46 lines vs master's 28), exporting
`RunnerHeartbeat` and `summarizeFleetHealth`. Its endpoint is the other half:
`web/server/api/fleet-health.get.ts`, 22 lines in the sweep against **3** on
master — which reads like a stub until you look at what the 3 lines call.

The two sides are **two complete implementations of the same feature**, each
internally consistent and each with its own passing test suite:

| | master | sweep `7ba40cac` |
|---|---|---|
| source of truth | `sentinel_state.json` on disk, four fallback paths | Supabase `runner_heartbeats`, service-role client, 500-row query |
| entry point | `readFleetHealth()` | `summarizeFleetHealth()` |
| returns | `{ db_up }` | `{ db_up, status, heartbeat_seconds, machines_live, contract_consistent }` |
| type | `web/types/fleet-health.ts`, 12 lines | same path, 17 lines |
| test | `readFleetHealth`: explicit-true only; fail-soft on false, missing, malformed and deleted state | `summarizeFleetHealth`: healthy fleet, degraded on mixed runner contracts, stale heartbeats not counted live |
| failure mode | returns `{ db_up: false }`, never a 500 | catch-all returning `status: 'unknown'` |

Master's version is not a degraded remnant. It has its own tests, its own
fail-soft path documented in comments, and a deliberate property the sweep's does
not have: **the web surface needs no database reachability to render a health
badge**, and holds no service-role client to do it with.

The sweep is six days newer than master's trio (master last touched all three
files in `fbb735b3`, 2026-08-07; the sweep is 2026-08-13), so this is not "master
moved on". It is a parallel design that was never merged, which is exactly why the
reconciler could not classify it as stale.

Swapping a tested implementation for a differently-tested one — and reintroducing
a service-role DB query into the web surface — is an owner's call about how fleet
health should be measured. It is not a recovery, and a reconciliation task is the
wrong place to make it.

**Recorded, not applied.** If the richer telemetry is wanted, the work exists at
`7ba40cac` and this note says where.

## The schema hazard, as requested — real, and already in master's history

`supabase/migrations/20260811160000_paused_host_release_guard_v2.sql` exists on
BOTH sides at the same timestamp with **different content**: 50 lines in the
sweep, 96 on master, different blob SHAs. That is the hazard shape the task asked
about.

It is not the sweep that created it. Master's copy was rewritten in place by
`16f12341` (2026-08-17, `agent: chatgpt-local-reconcile-beethoven-e0945946bd0d`) —
**after** a migration at that timestamp existed. Editing an already-applied
migration does not block `migrate deploy`, but it drifts the recorded checksum
against `_prisma_migrations`, and the drift only surfaces later as a confusing
`migrate status`.

The five lines the sweep has and master lacks are entirely **explanatory
comments** — the header explaining that trigger-side writes and `NOTIFY` roll back
with the rejected release, so the runner records the durable alert in a separate
transaction, plus the same reasoning inside a `COMMENT ON`. Useful rationale, and
still not worth restoring: adding comment lines to an applied migration drifts its
checksum again for zero functional gain. The rationale is preserved here instead.

**Reported, not fixed:** whether master's rewritten migration matches what is
actually applied in the database is a live-DB question this task cannot answer
from git, and it is worth someone checking.

## The other 16 files

None exports a symbol master lacks. Every one is the same surface at a slightly
different revision — the working set of an in-progress session, snapshotted four
times:

`runner/release_train.py` (1649 vs master 1714), `runner/tests/test_paused_host_scope.py`
(293 vs 314), `web/vitest.config.ts` (38 vs 45) — master ahead.
`components/{DevelopmentTerminal,FleetHealthBadge,ProofTimeline}.vue`,
`composables/{useFleetHealth,useOrchestratorSnapshot}.ts`,
`pages/orchestrators/[slug].vue`, `server/api/{orchestrator/snapshot,terminal/execute}.get/post.ts`,
`server/utils/releaseSurface.test.ts`, `types/fleet-health.ts` — sweep marginally
ahead, all of it the presentation layer of the same fleet-health design decision
above. `pages/index.vue` is 695 lines on both sides.

Taking any of them piecemeal would leave the tree half-way between two designs,
which is worse than either.

## Reproducing this

```
python3 runner/tools/reconcile_orch_rescue.py --repo . --base origin/master
git diff origin/master 7ba40cac -- <path>          # per-file semantic diff
git rev-parse 7ba40cac:<path> origin/master:<path> # blob identity
```
