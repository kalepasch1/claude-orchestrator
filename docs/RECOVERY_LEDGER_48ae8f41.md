# Recovery reconciliation — audit fingerprint `48ae8f4136…e0bb09`

Project: **beethoven** (claude-orchestrator) · base: `origin/master` @ `d3a6b47a`
· reconciled 2026-08-16

## Result

| Classification | Commits |
|---|---:|
| SUPERSEDED_BY_NEWER | 370 |
| ACTIVE_IN_ANOTHER_TASK | 93 |
| ALREADY_PRESENT | 74 |
| RECOVERABLE_VALUE | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 0 |
| **UNKNOWN** | **0** |

578 refs under `refs/orch-rescue/**` → 537 distinct commits. **Zero UNKNOWN.**
One `coordination_tasks` `recovery_ledger` record per commit (537 rows, 537
distinct shas — verified, no duplicates).

## Nothing needs recovering, and the 29 that looked like they did

The structural pass left 29 items with apparent value. Measuring what applying
each would actually do to `master` split them cleanly in two.

**26 are ancient.** Replaying any is a mass deletion — `5152ab956`, `9c023d06b`
and `ad00f1c96` would each add 3,763 lines and remove **400,542**; `12001806d`
adds 2,328 and removes 213,514; `364b3d7a0` adds 1,645 and removes 199,242.
These are snapshots of a tree from long before `master` grew into what it is.

**3 are live work belonging to sibling tasks**, and they are the interesting
ones because they invert the usual signal: `427067448` (+146,856 / −97),
`768fbf8d3` (+35,258 / −76) and `ccf5b04ab` (+34,819 / −33) are almost pure
addition. A near-zero deletion count means "this snapshot is ahead of master",
which normally reads as recoverable.

Reading what they add settles it — `docs/recovery-ledger-*.json`,
`docs/reconciliation/chatgpt-local-reconcile-beethoven-*.{json,md}`,
`scripts/orch-reconcile-evidence.mjs`, `runner/tools/reconcile_orch_rescue.py`.
That is the in-flight output of **concurrent sibling reconciliation tasks**,
taken off `fix/session-20260816-repairs` and a detached worktree at 18:48–20:05
today. Dozens of `origin/agent/chatgpt-local-reconcile-beethoven-*` branches
already exist. Recovering that work here would duplicate live tasks and race
them, so it is recorded as `ACTIVE_IN_ANOTHER_TASK` and left alone.

## On the sibling `reconcile-rescue-refs.mjs`

One sibling snapshot carries a 244-line script of the same name as the one added
here, so this is a genuine convergence rather than an oversight. Neither is on
`master`; both sit on unmerged agent branches, and the merge train will settle
them.

The version added here is kept because it carries three safety rules the
244-line version does not have, each of which changed a real verdict:

- **Sweep provenance.** Judging `On <branch>: periodic sweep` snapshots by the
  fate of their source branch rather than by whether their diff applies.
- **Strict-subset / delta direction.** A snapshot that only *removes* paths the
  base has is `SUPERSEDED_BY_NEWER`, never recoverable — it applies cleanly
  precisely because it is older.
- **Scratch-path filtering.** `.recovery-intent-*`, `.commit-message`,
  `.deploy-canary` and friends are orchestrator bookkeeping the base never
  tracks, so counting them as "new content" defeats the staleness test outright.

In the sibling project `pareto-2080` those three rules took the recoverable
count from **61 to 0**, and the last three false positives there predated a
fail-closed RIA compliance gate — recovering them would have stripped it back
out and shipped that as a recovery.

## Guarantees

- **Evidence untouched.** The classifier only reads; no delete/reset/clean/pop,
  patches dry-run via `git apply --check`.
- **No legacy-over-current**, and no duplication of live sibling work.
- **Zero UNKNOWN is enforced** — the script exits non-zero otherwise.

```bash
node scripts/reconcile-rescue-refs.mjs --base origin/master \
  --namespaces refs/orch-rescue --json ledger.json
```
