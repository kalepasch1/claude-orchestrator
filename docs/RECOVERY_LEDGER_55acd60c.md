# Recovery reconciliation — audit fingerprint `55acd60c79b1…a6c8c27`

Project: **beethoven** · base: `origin/master` · reconciled 2026-08-16

## Result

| Classification | Commits |
|---|---:|
| SUPERSEDED_BY_NEWER | 370 |
| ALREADY_PRESENT | 74 |
| ACTIVE_IN_ANOTHER_TASK | 93 |
| RECOVERABLE_VALUE | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 |
| **UNKNOWN** | **0** |

578 refs under `refs/orch-rescue/**` → 537 distinct commits.
**Zero UNKNOWN.** One `coordination_tasks` `recovery_ledger` record per commit.

```bash
node scripts/reconcile-rescue-refs.mjs --base origin/master \
  --namespaces refs/orch-rescue --json ledger.json
```

## Disposition

**Nothing in this evidence pile still holds unshipped value**, so no follow-up
task was queued — queueing one would be busywork, not provenance.

This is the same 578-ref pile audited under fingerprint `48ae8f413643`, and it classifies identically — the classifier is deterministic, so a second audit reproduces the first rather than drifting.

Twenty-nine items survived the structural pass. **Twenty-six are ancient**: `5152ab956`, `9c023d06b` and `ad00f1c96` would each add 3,763 lines and remove **400,542**; `12001806d` adds 2,328 and removes 213,514.

**Three invert the usual signal** and are worth naming: `427067448` (+146,856 / −97), `768fbf8d3` (+35,258 / −76) and `ccf5b04ab` (+34,819 / −33) are almost pure addition, which normally reads as clearly recoverable. What they add is `docs/recovery-ledger-*.json`, `docs/reconciliation/*`, `scripts/orch-reconcile-evidence.mjs` and `runner/tools/reconcile_orch_rescue.py` — the in-flight output of **concurrent sibling reconciliation tasks**, swept off `fix/session-20260816-repairs` at 18:48–20:05 the same day, with dozens of matching `origin/agent/chatgpt-local-reconcile-beethoven-*` branches already present. Recovering that here would duplicate and race live work, so it is recorded `ACTIVE_IN_ANOTHER_TASK` and left alone.

## How the classifier avoids recovering a regression

Every item here is an `orch-rescue: periodic sweep` — a snapshot of an agent
branch's *uncommitted* worktree taken by a crash sweep, not an authored commit.
Its worth is derivative of the branch it came from, so the useful question is
not "does this patch apply?" but "did the branch it came from already land?"

Judged naively by whether the diff replays cleanly, these piles read as far
more recoverable than they are. Three rules do the real work:

- **Sweep provenance** — resolve each snapshot's source branch. Merged ⇒ stale
  by construction; still live ⇒ already owned by that branch's task.
- **Delta direction** — a snapshot that only *removes* paths the base has is
  `SUPERSEDED_BY_NEWER`, never recoverable. It applies cleanly precisely
  because it is older.
- **Scratch-path filtering** — `.recovery-intent-*`, `.commit-message`,
  `.deploy-canary` are orchestrator bookkeeping the base never tracks, so
  counting them as "new content" silently defeats the staleness test.

In the sibling project `pareto-2080` those rules took the recoverable count
from **61 to 0**, and the last three false positives there predated a
fail-closed RIA compliance gate — recovering them would have stripped it out
and shipped that as a recovery.

## Guarantees

- **Evidence untouched.** The classifier only reads — no delete, reset, clean,
  pop or move; patches are dry-run via `git apply --check`.
- **No legacy-over-current.** The newest implementation always wins.
- **Zero UNKNOWN is enforced**, not asserted — the script exits non-zero if any
  item is left unclassified.
