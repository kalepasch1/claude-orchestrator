# ChatGPT/Codex local build-evidence reconciliation — beethoven (orchestrator rescue refs)

- Audit fingerprint: `8d0702cbd5aa9e9fd4343cdf42c20f73f498d32891d59b1685a1bbe136065a62`
- Task: `chatgpt-local-reconcile-beethoven-8d0702cbd5aa`
- Evidence source: `/Users/kpasch/Documents/beethoven/claude-orchestrator` — `refs/orch-rescue/*` (read-only; nothing deleted, reset, cleaned, popped or moved)
- Refs enumerated from the live source: **577**
- UNKNOWN items: **0**
- Machine-readable ledger: `.orch/recovery-ledger-8d0702cbd5aa.json`

## Classification summary

| Classification | Count |
|---|---|
| ALREADY_PRESENT | 112 |
| SUPERSEDED_BY_NEWER | 227 |
| ACTIVE_IN_ANOTHER_TASK | 0 |
| RECOVERABLE_VALUE | 16 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 222 |

## Recovered value

12 refs carried paths absent from `origin/master`, recovered once each:

- **rescue-ref reconciliation tooling** — `runner/tools/reconcile_orch_rescue.py`,
  `scripts/{orch-reconcile-evidence,reconcile-rescue-refs,recovery-ledger-report}.mjs`,
  `tools/map_snapshot_evidence.mjs`. This is the tooling that makes passes like this one
  reproducible instead of hand-rolled.
- **tests that pass against the current tree** — `runner/tests/test_reconcile_orch_rescue.py` (12),
  `runner/tests/test_merge_train_structure.py` (5), `runner/test_contracts_smarter.py` (69),
  `tools/map_snapshot_evidence.test.mjs` (8).
- `runner/stderr_digest.py`, `packages/spine/shared/contracts/pipeline.ts`,
  `packages/darwin-kernel/test/spine-contracts.consumer.ts`
- `supabase/migrations/20260811160000_paused_host_release_guard_v2.sql`
- ~40 prior-pass recovery ledgers and reconciliation docs

### Excluded as state or malformed paths, not source

`node_modules*`, `__pycache__/*.pyc`, `runner/.preopt_cache/*`, `runner/.restart_requested`,
`.runner_boot_commit`, `.claude/settings.local.json`, a loose `.patch`, and two entries that were
not paths at all (`unittest.main()`, `Updated show_greeting.py`) — artifacts of malformed diffs.

### Deferred — recovered, then held back

Six recovered test files assert against NEWER versions of modules `origin/master` already carries,
so their subjects sit in the CONFLICTED set and were not replayed. Shipping the tests without the
subjects would put the train red for a reason unrelated to this recovery:

| Test | Missing symbol |
|---|---|
| `runner/tests/test_bandit_performance_tracker.py` | `bandit.PerformanceTracker`, `bandit._z_for` |
| `runner/tests/test_priority_queue_roi.py` | ROI pinning in `priority_queue` |
| `runner/tests/test_20260816_card_loop_and_stderr.py` | `merge_train._recently_finalised` |
| `runner/tests/test_20260817_prepare_toolchain.py` | `release_train.PREPARE_TIMEOUT_S`, `_local_bin` |
| `runner/tests/test_20260816_branch_share_fetch.py` | one case against newer branch-share behaviour |
| `scripts/reconcile-evidence.test.mjs` | `buildPreservationPlan` export |

Follow-up: `beethoven-reconcile-followup-deferred-tests-newer-module-versions`.

## Verification

Every recovered path is ABSENT from `origin/master` — that is the classification criterion — so no
existing file was modified and no existing test can regress. What was verified is the recovered
material itself:

- `pytest runner/tests/test_reconcile_orch_rescue.py runner/tests/test_merge_train_structure.py runner/test_contracts_smarter.py` -> **86 passed**
- `node --test tools/map_snapshot_evidence.test.mjs` -> **8/8**
- `node --check` passes on all four recovered `.mjs` scripts

## Conflicts queued, not forced

222 refs modify paths `origin/master` already carries. Left intact and queued as
`beethoven-reconcile-followup-222-conflicted-rescue-refs`, pointing at the per-ref list in the
JSON ledger.

## Provenance

- RECOVERABLE_VALUE -> branch `agent/chatgpt-local-reconcile-beethoven-8d0702cbd5aa` (this commit).
- CONFLICTED / deferred -> two queued follow-up tasks, named above.
- Every `refs/orch-rescue/*` ref remains intact in the local repository.

