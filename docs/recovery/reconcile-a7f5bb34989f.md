# ChatGPT/Codex local build-evidence reconciliation — beethoven (dirty worktrees)

- Audit fingerprint: `a7f5bb34989fffd2ef3e1ca6afd3da6107ba540d9848a46a9114652e8f09a2ea`
- Task: `chatgpt-local-reconcile-beethoven-a7f5bb34989f`
- Evidence kind: `dirty_worktree` (+ the broken-worktree and bridge-artifact classes
  the same reconciler owns)
- Evidence source: registered worktrees of `/Users/kpasch/Documents/beethoven/claude-orchestrator`
  and `~/Documents/chatgpt-dropbox` — both read-only
- Items enumerated: **33**
- UNKNOWN items: **0**

## Classification summary

| Classification | Count |
|---|---|
| ALREADY_PRESENT | 24 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 7 |
| RECOVERABLE_VALUE | 2 |
| SUPERSEDED_BY_NEWER | 0 |
| ACTIVE_IN_ANOTHER_TASK | 0 |

Ledger: `.orch/recovery-ledger-a7f5bb34989f.json` (one record per item, with source,
classification, disposition and the files it touches).

## The classifier was wrong, and the fix is the code change on this branch

This pass was run with `tools/reconcile_worktree_evidence.py`, reusing the existing
reconciler rather than writing a new one. Its first run reported
`~/Documents/beethoven/claude-orchestrator-wt/spine-types-x2` as **RECOVERABLE_VALUE**
on the strength of one untracked file, `packages/spine/package-lock.json`.

That file is on `origin/master`, byte-identical. "Untracked" is relative to the
worktree's own checkout, and `spine-types-x2` is parked on a commit older than the one
that added the path — so every stale worktree manufactured phantom recoverable value,
and a reviewer chasing it would find work that was never lost.

`classify_worktree` took the untracked-only path straight to `RECOVERABLE_VALUE` with
no comparison against `base`. This branch adds that comparison:

- `base_blob(base, path, repo)` — blob sha the base carries for a path, `""` when it
  does not carry it. Fail-soft: a git error reads as "not in base", never raises.
- `worktree_blob(root, path)` — what the working-tree file hashes to, `""` when absent.
- `split_untracked_against_base(...)` — partitions untracked paths into
  new / identical-to-base / diverged-from-base.

The untracked-only branch now resolves to ALREADY_PRESENT when every path matches the
base, CONFLICTED_NEEDS_FOCUSED_TASK when paths exist in the base with different content
(overwriting the newer tracked version is exactly what the recovery contract forbids),
and RECOVERABLE_VALUE only for paths the base genuinely lacks.

`tools/test_reconcile_worktree_evidence.py` covers all six cases against real git repos,
including both fail-soft paths. `python3 -m unittest discover -s tools -p 'test_*.py'`
is green.

With the fix, `spine-types-x2` reclassifies to ALREADY_PRESENT and the dirty-worktree
class carries **zero** false recoverables.

## The two items that still hold value are not beethoven's to recover

Both RECOVERABLE_VALUE items are bridge artifacts in `_applied/` — the bridge recorded
them as landed, but their diffs still apply cleanly to their target's default branch,
so the change never actually reached it:

- `20260817-192242--apparently--absorb-otc-payoff-slice1-20260817.patch`
- `20260817-201758--apparently--absorb-otc-payoff-slice1-v2-20260818.patch`

They target **`apparently`**, not this repo: `server/utils/otc/payoffDSL.ts`,
`server/utils/otc/compositePayoffCompiler.ts`, its test, and
`docs/absorption/STATUS-20260817.md`. Replaying them here would be meaningless. They are
queued as a focused follow-up against the `apparently` project (the v2 patch supersedes
the v1 of the same slice; the follow-up carries both so the reviewer picks the newer).

## Deferred, with the reason recorded

The 7 CONFLICTED items are not dropped value — each is recorded with why it stayed put:

- Three `-wt/` worktrees hold the same uncommitted pair
  (`runner/economic_scheduler.py` + `runner/tests/test_economic_scheduler_failsoft_repro.py`)
  whose diff no longer applies to master.
- Two Codex session worktrees (`orchestrator-visibility-remediation`,
  `orchestrator-session-fabric-current`) hold a broad `web/` + `runner/release_train.py`
  change, including a `paused_host_release_guard_v2` migration under two different
  timestamps. Forcing either over master would overwrite newer release-train work.
- Two failed/pending bridge artifacts whose patches no longer apply.

## Provenance

- Every worktree was inspected in place. Nothing was stashed, cleaned, checked out,
  reset, pruned or moved. No `refs/orch-rescue/*` ref was touched.
- This task's own worktree is excluded from its own evidence (`--exclude-path`);
  otherwise the reconciler reports its own in-progress edits as recoverable.
- Source files changed by this branch: `tools/reconcile_worktree_evidence.py` and its
  new test. No recovered content is introduced here, so this branch does not collide
  with the sibling reconciliation branches.
