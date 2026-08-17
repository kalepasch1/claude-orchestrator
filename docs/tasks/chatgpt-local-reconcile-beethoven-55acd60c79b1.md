# Recovery reconciliation — audit fingerprint `55acd60c79b1…a6c8c27`

Project **beethoven** · base `origin/master` @ `d3a6b47a` · attempt 3 (re-delivery)

## Why this attempt exists

The classification was never the problem. Attempt 2 reconciled the same pile and
reached zero UNKNOWN. It failed to land because of *what it committed*, not what
it concluded: it put `scripts/reconcile-rescue-refs.mjs` — a shared, non-slug-named
path that several concurrent reconcile tasks all touch — into the delivery commit,
and the merge train stalled on the collision.

This attempt re-delivers the same verdicts from a branch cut fresh off
`origin/master` and commits **only fingerprint- and slug-named files**:

    .orch/recovery-ledger-55acd60c.json
    docs/tasks/chatgpt-local-reconcile-beethoven-55acd60c79b1.md

The classifier itself was re-run from `/tmp`, outside the working tree, so it
could be reused without being re-committed.

## Result

| Classification | Distinct sources | Refs |
|---|---:|---:|
| SUPERSEDED_BY_NEWER | 367 | 370 |
| ACTIVE_IN_ANOTHER_TASK | 96 | 96 |
| ALREADY_PRESENT | 74 | 112 |
| RECOVERABLE_VALUE | 0 | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 | 0 |
| **UNKNOWN** | **0** | **0** |

Evidence: **577 refs under `refs/orch-rescue/**` → 536 distinct commits**, plus the
one `dirty_worktree` item named in the task snapshot
(`claude-orchestrator-wt/evrouter`) = **537 distinct sources / 578 evidence items**.
One `coordination_tasks` record per evidence item under this fingerprint.

## Two passes, and why the second one exists

The **structural pass** (ancestry, live-branch reachability, delta direction,
scratch-path filtering) leaves 29 survivors: 27 `RECOVERABLE_VALUE` and 2
`CONFLICTED_NEEDS_FOCUSED_TASK`. Taken at face value that reads as real recoverable
work. It is not, and the **second pass** says why, per item, mechanically:

- **Net-destructive snapshots — 26 items.** Every one removes far more than it
  adds against `origin/master`: `5152ab95`, `9c023d06` and `ad00f1c9` are each
  `+3,763 / −452,742`; `a4a7ec82` is `−373,123`; `958f7ef5` is `−306,443`;
  `d0eb2024` is `−306,443`. A snapshot that applies cleanly *because* it predates
  a batch of landings is older than the base by construction. Replaying it would
  delete live code and ship the regression as a recovery. → `SUPERSEDED_BY_NEWER`.
- **Concurrent reconcile output — 3 items.** `42706744` (`+146,864 / −97`),
  `768fbf8d` (`+35,266 / −76`) and `ccf5b04a` (`+34,827 / −33`) invert the usual
  signal: almost pure addition. What they add is `docs/reconciliation/*`,
  `docs/recovery-ledger-*.json` and `.recovery-intent-*` — the in-flight output of
  sibling `chatgpt-local-reconcile-beethoven-*` tasks that are RUNNING right now,
  swept off `fix/session-20260816-repairs`. Recovering it here would race and
  duplicate live work. → `ACTIVE_IN_ANOTHER_TASK`.

26 + 3 = 29. That is the same split the first audit reached, reproduced from a
clean run rather than copied — the classifier is deterministic, so a second audit
reproduces the first rather than drifting.

## Drift since attempt 2

Attempt 2 saw 578 refs / 537 distinct commits and recorded 370 / 93 / 74. This run
sees **577 refs / 536 distinct commits** and adjudicates **367 / 95 / 74** (+1
`ACTIVE_IN_ANOTHER_TASK` for the dirty worktree = 96). One rescue ref was pruned by
the sweep between the two runs, and live-branch reachability moved two items from
SUPERSEDED to ACTIVE as sibling branches advanced. Nothing moved *into* recoverable
value. The published ledger is topped up idempotently on `(audit_fingerprint,
source)`; prior records were not deleted or rewritten.

## Disposition

**Nothing in this pile still holds unshipped value**, so no follow-up task was
queued. Queueing one would be busywork, not provenance.

## Guarantees

- **Evidence untouched.** Read-only throughout — no delete, reset, clean, pop or
  move. Patch viability is probed with `git apply --check` only.
- **No legacy-over-current.** The newest implementation always wins; net-destructive
  snapshots are never recoverable however cleanly they replay.
- **Zero UNKNOWN is enforced, not asserted** — the classifier exits non-zero if any
  item is left unclassified, and the ledger carries an explicit `unknown` count.
- **No shared paths in the commit.** Only the two files named above, which is the
  root cause this attempt was opened to fix.
