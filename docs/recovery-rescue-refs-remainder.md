# Recovery: remaining orchestrator rescue refs (backlog-batch and remainder)

Audit fingerprint `5dc36bf5e0bed6f108545572d49189cbfbc558ee98ae1290254e2e125f7e5918`.
Ledger: `.orch/recovery-ledger-5dc36bf5e0be-combined.json` on
`agent/chatgpt-local-reconcile-beethoven-5dc36bf5e0be`.

Filter: `classification == RECOVERABLE_VALUE`, `kind == orchestrator_rescue_refs`
(42 refs), minus the clusters owned by the three sibling group tasks —
scanner-and-queue-health, test-routing-and-relfix, session-fabric-and-visibility.
**Remainder: 24 refs.** Every ref is untouched: nothing deleted, reset, cleaned,
popped or moved.

## Method — read this before working the next batch

Diffing a rescue ref against `origin/master` is meaningless and actively
misleading. These refs are stash-like snapshots taken against a master that has
since moved thousands of commits, so `git diff origin/master <ref>` reports
things like `+4410/−956242 across 2068 files` — almost entirely the *rest of the
repo the snapshot predates*, not the work.

Diff against the merge base instead:

```bash
git diff $(git merge-base origin/master <ref>) <ref>
```

The same 24 refs then resolve to deltas of 1–20 files each. Classification is
then a mechanical three-way test per ref, run in a worktree at `origin/master`:

```bash
git apply --check --reverse patch   # succeeds => ALREADY PRESENT
git apply --check         patch     # succeeds => APPLIES CLEAN
# neither                           => CONFLICTS (master diverged)
```

## Landed (9 refs)

| ref | delta | what it is |
|---|---|---|
| `bedc007c` missing-branch-auto-creator | `runner/tests/test_auto_remediate.py` +36 | test that decomposition completion fires `greedy_dispatch.on_decomposition_complete` |
| `aa3c1231` high-performance-database | `config_store.py`, `fleet_control.py` + tests +163/−32 | config-store integration |
| `12001806` bandit | `runner/bandit.py` +589, new `test_bandit_performance_tracker.py` | `PerformanceTracker` + acceptance gate (see repair note) |
| `7bf01722` fix-canonical-enqueue | `enqueue_task.py`, `pipeline_contract.py` +183/−41 | canonical enqueue trigger regression fix |
| `28c0982f` fleet-immune throughput | `runner/slo_controller.py` +64 | speed/triage routing accelerator |
| `649efcae` c27-minimal | `runner/tests/test_template_95fc17a.py` +55/−67 | later of two snapshots |
| `26b72d0b` backlog-batch a86bb21 | `express_lane.py` + test +62/−3 | pinned express lane recovery |
| `95167518` lease-night-g1 | `packages/darwin-kernel/src/passport/passport.ts` +63/−11 | `CLAIM_KINDS` grouped registry — restructures the union that caused four merge-train failures |
| `87d761c1` backlog-batch d3151d8 | `runner/priority_queue.py` +78/−12 | later of two snapshots |

### Repair required to land `12001806` (bandit)

The rescue ref does not run. Its `bandit.py` references `ACCEPTANCE_CONFIDENCE`,
`ACCEPTANCE_MIN_SAMPLES`, `ACCEPTANCE_ENABLED` and `_Z` and defines none of them
— the snapshot was taken mid-edit, so all 46 of its own tests raise `NameError`
in `setUp`. The definitions were reconstructed from the call sites and from what
the recovered tests assert (`BANDIT_ACCEPTANCE` kill switch via module reload,
`BANDIT_ACCEPT_MIN_SAMPLES` floor, `_z_for(0.95) ≈ 1.96`, `_z_for(0.99) ≈
2.576`):

- `ACCEPTANCE_ENABLED` / `ACCEPTANCE_CONFIDENCE` / `ACCEPTANCE_MIN_SAMPLES`,
  read at import time like the neighbouring `EPSILON` so the kill switch works
  by reload, defaults `true` / `0.95` / `12`.
- `_Z`, a seven-entry two-sided normal critical-value table (kept as a table, not
  an inverse-erf, so the module stays dependency-free and the values are
  auditable).

**This is the single highest-value item in the batch** — an acceptance gate that
stops the router paying to re-explore a comparison it has already settled — and
it was one undefined constant away from being lost.

## Already present on master (2 refs)

`7071d96c` (`tests/test_core_retry_rpcs.py`) and `51a1a5e0`
(`runner/merged_diff_library.py`) reverse-apply cleanly: the work landed by
another path. No action.

## Superseded duplicates, not landed (5 refs)

Successive snapshots of a ref that was landed from its newest version. Landing
both would be the double-apply the prompt warns about.

`cd80d50c` (dup of `7bf01722`), `dcf328aa` + `739d0d24` + `814604f7`
(pinned-express, all three superseded — see conflicts below), `680be7c7` (dup of
`649efcae`), `50dd28e3` (dup of `26b72d0b`), `d2055a73` (dup of `87d761c1`).

## Conflicts — need focused tasks (5 refs)

Master has diverged in the same regions; force-landing would revert newer work.
Each needs a human-scale merge, not a batch apply:

- `9225b0f5` dropbox-operator-gate-amendment — `fleet_contracts.py`,
  `fleet_control.py` +307
- `4fb310c6` fix-compilation-types — 29 files across `web/` and
  `packages/darwin-kernel` +131/−43
- `3213f4fa` audit-addendum group-5 — 20 files, +3060, git-identity / clean-clone
  / sentinel work
- `90a1e704` canary-claude-27 — 8 files, +53/−9
- `814604f7` / `dcf328aa` / `739d0d24` pinned-express —
  `runner/tests/test_pinned_express_lane.py`

## Tool noise, not landed (1 ref)

`423c51ca` deployfix — the whole delta is `.vercel/project.json` being
pretty-printed and re-cached by the Vercel CLI. No content.

## Verification

- `runner.tests.test_bandit_performance_tracker` — 46 tests, green (0 before the
  repair above).
- `test_fleet_control`, `test_fleet_express_lane`, `test_template_95fc17a`,
  `test_auto_remediate` — 77 tests, green apart from
  `test_max_turns_escalates_at_cap` / `test_max_turns_retries_under_cap`, which
  **fail identically on clean `origin/master`** (`StopIteration` on an
  exhausted mock `side_effect`) and are unrelated to this recovery.
- `test_enqueue_trigger_regression`, `test_pipeline_contract`,
  `test_pipeline_contract_allowlist`, `test_slo_controller`,
  `test_slo_controller_like_syntax`, `test_recovery_priority`,
  `test_enqueue_task_loader` — 42 tests, green.

## Cross-check against live branches

The 11 refs the same ledger classifies `ACTIVE_IN_ANOTHER_TASK` were never in
scope: the filter selects `RECOVERABLE_VALUE` only. The two refs that master
already carries were caught by the reverse-apply test above rather than by
trusting the classification.
