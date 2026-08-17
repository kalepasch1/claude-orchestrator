# chatgpt-local-reconcile-beethoven-8d0702cbd5aa

Audit fingerprint: `8d0702cbd5aa9e9fd4343cdf42c20f73f498d32891d59b1685a1bbe136065a62`
Base: `origin/master` @ `d3a6b47abff44f2cc41bb952ce81cd48595d0cfc`
Branch: `agent/chatgpt-local-reconcile-beethoven-8d0702cbd5aa`
Attempt: 2 (agentic repair, category `conflict`)
Ledger: `.orch/recovery-ledger-8d0702cb.json`

## Why attempt 1 was rejected, and what changed

Attempt 1 classified the evidence correctly. It lost the merge train on packaging.

The repair directive named `.orch/recovery-ledger-8d0702cbd5aa.json` as the conflicting
file. That name was claimed by two branches at once: this task's own
`7decb6e7`, and the sibling `48ae8f413643` branch, which had been cut on top of
this branch instead of on `origin/master` and therefore carried an identical copy of
the same path. Two branches offering the same new file is an unresolvable add/add
conflict, no matter how good the contents are.

Attempt 1 also shipped `tools/map_snapshot_evidence.mjs` and its test, which already
exist byte-identical on `origin/agent/chatgpt-local-reconcile-beethoven-6c8911116873`,
plus `docs/recovery-ledger/8d0702cbd5aa.json`, a second copy of the same ledger. A
later local commit (`6a56c222`) grew the delta to 70 files, most of them other tasks'
ledgers swept in from the dirty main working tree.

The repair:

- cut fresh from `origin/master` in an isolated worktree, not from any sibling branch
  or integration overlay;
- key the ledger to the first eight characters of this task's own fingerprint
  (`recovery-ledger-8d0702cb.json`), a name no other branch can produce;
- ship exactly two files — the ledger and this note. The duplicate ledger copy, the
  `map_snapshot_evidence` pair, and every swept-in sibling deliverable are dropped.

Attempt 1's classifications are preserved verbatim and re-verified, not recomputed.
Its tips are kept additively at
`refs/orch-preserved/chatgpt-local-reconcile-beethoven-8d0702cbd5aa-attempt1-7decb6e7`
and `...-attempt1-6a56c222`.

## Re-verification against the live source

The base has not moved since attempt 1 (`d3a6b47a` both times), so no verdict was
invalidated by a base change. The live evidence source was re-enumerated anyway:

- `refs/orch-rescue` now holds 576 refs. Nine are new since attempt 1 and are
  classified in this pass; seven refs attempt 1 saw are no longer present. Retired
  refs keep their verdict and are flagged `live_at_reverification: false` — the
  evidence source is read-only, so nothing was deleted, reset, cleaned, popped or moved
  by this task.
- The nine new refs are all sweeps of branches that are still owned elsewhere: five of
  this task's own branch and of sibling reconcile branches, one of
  `agent/release-on-capacity-not-clock-cowork-20260806`, and one sweep of the main
  working tree whose 85 paths are sibling reconcile ledgers, each already carried by
  its own agent branch.

## Classification

654 evidence items, **0 UNKNOWN**.

| Classification | Count |
| --- | --- |
| SUPERSEDED_BY_NEWER | 293 |
| ALREADY_PRESENT | 235 |
| RECOVERABLE_VALUE | 61 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 53 |
| ACTIVE_IN_ANOTHER_TASK | 12 |

By evidence kind:

| Kind | AP | SBN | AIAT | RV | CNFT |
| --- | --- | --- | --- | --- | --- |
| orchestrator_rescue_refs | 192 | 285 | 11 | 52 | 43 |
| local_only_branch_tips | 10 | 6 | 1 | 1 | 3 |
| dirty_worktree | 4 | 0 | 0 | 6 | 5 |
| snapshot:orchestrator_rescue_refs | 27 | 2 | 0 | 0 | 1 |
| broken_codex_git_worktree | 1 | 0 | 0 | 0 | 0 |
| snapshot:broken_codex_git_worktree | 0 | 0 | 0 | 1 | 0 |
| chatgpt_bridge_artifact | 0 | 0 | 0 | 1 | 0 |
| snapshot:chatgpt_bridge_artifact | 1 | 0 | 0 | 0 | 0 |
| codex_output_artifact | 0 | 0 | 0 | 0 | 1 |

`ALREADY_PRESENT` is decided by `git merge-base --is-ancestor <sha> origin/master`,
never by branch-name matching. `SUPERSEDED_BY_NEWER` covers the net-destructive case:
a snapshot whose delta is mostly deletions of paths still present on the base predates
the base and applies cleanly only because it is older — recovering it would be a
regression.

## Durable provenance for everything with remaining value

Nothing is recovered into source on this branch; the deliverable is the ledger.
Remaining value is carried by tasks already live in the queue, which is where the
recovery contract wants it:

- `beethoven-reconcile-followup-222-conflicted-rescue-refs`
- `beethoven-reconcile-followup-8-conflicted-local-tips`
- `beethoven-reconcile-followup-deferred-tests-newer-module-versions`
- `beethoven-followup-land-open-chatgpt-bridge-prs`
- `recover-rescue-refs-group-backlog-batch-and-remainder`
- `recover-rescue-refs-group-scanner-and-queue-health`
- `recover-rescue-refs-group-session-fabric-and-visibility`
- `recover-rescue-refs-group-test-routing-and-relfix`
- `recover-codex-worktree-orchestrator-session-fabric-current`
- `recover-codex-worktree-orchestrator-visibility-remediation`
- `recover-never-again-lane-daemon-dirty-worktree`
- `recover-bridge-artifact-operator-output-truth-session-fabric`

One `coordination_tasks` row per evidence item is published under this task's
fingerprint, carrying source, classification, disposition and the resulting
task/branch/commit.
