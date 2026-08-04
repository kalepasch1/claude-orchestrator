# Historical Code Recovery Sweep — every improvement ever lost to the overwrite bug, recovered or accounted for

Operator directive 2026-07-30. The legacy-overwrite class is FIXED at the source (verified at
HEAD: auto_conflict_resolver never whole-file-overwrites source files and routes add/add source
conflicts to ast_merge/manual; self_healing_merge runs in ephemeral worktrees and never
stashes/resets the main checkout; sentinel rescues operator work to hotfix branches and converts
any anonymous WIP stash into a permanent rescue branch). This sweep recovers what the bug ALREADY
cost us, so the current dev branch contains the optimal version of every improvement ever made.

## Inventory to process (all in the claude-orchestrator repo)
1. ~29 `hotfix/stash-rescue-*` branches (auto-created by wip_stash_rescue from the historical
   anonymous-stash pile) + `hotfix/stash-rescue-lease-night-5f879035` + any `hotfix/sentinel-rescue-*`.
2. The remaining unreconciled stashes (`git stash list`) — the labeled sentinel-drift ones.
3. The 12 previously-identified recoverable stashes and the ~120 conflicted stashes from the
   315-stash triage (state recorded in the earlier stash-audit artifacts/notes).
4. Any `agent/*` branches never merged whose merge-train verdict was the OLD resolver's
   "already_integrated" (spot-check: the old resolver could mark improvements integrated after
   overwriting them — re-verify a sample of 20 against actual file content).

## Method (per item — judgment, not blind patching)
- Work in worktrees per convention; never touch the main checkout.
- For each rescue branch/stash: 3-way merge each hunk against CURRENT master. Classify:
  (a) ALREADY PRESENT (landed later via another path) -> record, close;
  (b) SUPERSEDED (current code solves the same problem better) -> record the divergence, close —
      NEWER/OPTIMAL WINS, never resurrect legacy over current improvements;
  (c) RECOVERABLE VALUE (the improvement is absent and still correct) -> apply, test, land via
      the normal QA/merge path;
  (d) CONFLICTED/UNCLEAR -> queue a focused per-file task rather than forcing.
- The decision rule everywhere, verbatim: **the most up-to-date/optimal code wins; legacy never
  overwrites newer work, and newer work never gets resurrected-over by recovery.**
- Every item ends in the RECOVERY LEDGER (coordination_tasks task_type='recovery_ledger'):
  source ref, classification, disposition, commit/task link — so the operator can see that 100%
  of the historical pile is accounted for, item by item, in the progress console.

## Acceptance
- `git stash list` items and every rescue branch have a recovery_ledger row.
- Zero items in state "unknown"; (c)-class items merged or queued with tests.
- A final summary row: N recovered, N superseded, N already-present, N escalated — published to
  the progress console under "Fleet — Historical code recovery sweep".
