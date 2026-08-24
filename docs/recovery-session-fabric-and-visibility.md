# Recovery: orchestrator session-fabric + visibility rescue refs

Audit fingerprint `5dc36bf5e0bed6f108545572d49189cbfbc558ee98ae1290254e2e125f7e5918`.
Ledger: `.orch/recovery-ledger-5dc36bf5e0be-combined.json` on
`agent/chatgpt-local-reconcile-beethoven-5dc36bf5e0be`.

Filter applied: `classification == RECOVERABLE_VALUE`, `kind ==
orchestrator_rescue_refs`, ref matching `orchestrator-session-fabric-current` or
`orchestrator-visibility-remediation`. That is four refs:

| ref | sha | files vs master |
|---|---|---|
| `20260807T125256-orchestrator-visibility-remediation-15d8c552` | `15d8c55` | 15 |
| `20260807T130647-orchestrator-visibility-remediation-a05140c3` | `a05140c` | 16 |
| `20260811T152527-orchestrator-session-fabric-current-364b3d7a` | `364b3d7` | 15 |
| `20260813T034449-orchestrator-session-fabric-current-7ba40cac` | `7ba40ca` | 18 |

## Reconciliation

The four refs are successive snapshots of one body of work, not four bodies of
work. `7ba40cac` (the newest) is a strict file superset of the other three
except for `runner/tests/test_merge_truth.py`, which appears only in `a05140c3`
and lands in the excluded set below anyway. **One version was landed: the
`7ba40cac` snapshot.** No ref was applied twice.

All four refs are untouched — not deleted, reset, cleaned or moved.

## What was landed

The evidence/visibility surface, which is genuinely absent from master:

- `web/types/fleet-health.ts`, `web/composables/useFleetHealth.ts` — `FleetHealth`
  gains `status` / `heartbeat_seconds` / `machines_live` / `contract_consistent`.
- `web/server/utils/fleetHealth.ts` + `fleetHealth.test.ts` — replaces the
  read-a-local-`sentinel_state.json` implementation with `summarizeFleetHealth()`
  over the shared runner-heartbeat ledger. The file-reading version cannot work
  on Vercel, where there is no runner-written file to read.
- `web/server/api/fleet-health.get.ts`, `web/server/api/orchestrator/snapshot.get.ts`,
  `web/composables/useOrchestratorSnapshot.ts` — snapshot rows carry `kind`,
  `project_id`, `artifact_commit`.
- `web/components/FleetHealthBadge.vue` (prop `db-up` → `health`),
  `ProofTimeline.vue`, `DevelopmentTerminal.vue`.
- `web/pages/index.vue`, `web/pages/orchestrators/[slug].vue` — task-state
  vocabulary updated to `DEPLOYED_AND_VERIFIED` / `PHANTOM_UNVERIFIED`.
- `web/server/utils/releaseSurface.test.ts`.
- `web/vitest.config.ts` — the hermetic `css.postcss.plugins: []` line only
  (hand-applied, see exclusions).

**Verified before landing:** the new task states are not speculative. The live
`tasks` table holds 413 `DEPLOYED_AND_VERIFIED` and 660 `PHANTOM_UNVERIFIED`
rows, so master's dashboard — which renders both as "neutral" — is the stale
side of this diff, not the rescue ref.

`npx vitest run` in `web/`: **51 files, 504 tests, all passing.**

## What was deliberately NOT landed, and why

A rescue ref is a snapshot of a working tree from weeks ago. Applying it whole
does not just add its work — it *reverts* everything master learned since. Five
paths in `7ba40cac` are older than master and were dropped:

1. **`web/server/api/terminal/execute.post.ts`** — the ref replaces master's
   argv-allowlist serverless guard (`execFile`, no shell, shared
   `utils/terminalGuards`) with an inline regex prefix allowlist that shells
   out. That is a security regression, not a recovery. Master's version stands.
2. **`runner/release_train.py`** (−81 lines vs master) — superseded.
3. **`runner/tests/test_paused_host_scope.py`** (−48) — superseded.
4. **`supabase/migrations/20260811160000_paused_host_release_guard_v2.sql`**
   (−51) — superseded. (2–4 are the paused-host release guard, a different
   concern that merely shared a working tree with this one.)
5. **`web/vitest.config.ts` include-list narrowing** — the ref narrows
   collection back to `server/utils` + `server/engines`; master deliberately
   widened it to all of `server/**` after discovering 226 API routes were
   structurally untestable. Only the additive postcss line was taken.

## Sibling tasks

The prompt flags this cluster as triple-represented, with the same work also
sitting in two Codex worktrees and one never-landed `_applied` bridge patch
(`recover-codex-worktree-orchestrator-session-fabric-current`,
`recover-codex-worktree-orchestrator-visibility-remediation`,
`recover-bridge-artifact-operator-output-truth-session-fabric`).

**Those three tasks should now check against this branch before doing anything.**
The visibility surface is landed here once. If a sibling's representation
contains something this snapshot does not, land only that delta — do not apply a
second full copy.
