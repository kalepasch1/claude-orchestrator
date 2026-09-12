# ChatGPT/Codex local build-evidence reconciliation — beethoven (rescue refs + branch tips, second snapshot)

- Audit fingerprint: `03d851526d1e0c1682ae52960ca52ebe18572248d3ea76c8beb7b23e8376cdca`
- Task: `chatgpt-local-reconcile-beethoven-03d851526d1e`
- Evidence kinds: `orchestrator_rescue_refs`, `local_only_branch_tips`
- Evidence source: `/Users/kpasch/Documents/beethoven/claude-orchestrator`, read-only
- Items enumerated: **683**
- UNKNOWN items: **0**

## Classification summary

| Classification | Count |
|---|---|
| ALREADY_PRESENT | 264 |
| SUPERSEDED_BY_NEWER | 229 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 90 |
| RECOVERABLE_VALUE | 53 |
| ACTIVE_IN_ANOTHER_TASK | 47 |

Ledger: `.orch/recovery-ledger-03d851526d1e.json`, plus one `coordination_tasks` record
per item under this fingerprint.

## This branch adds no source file, and that is the finding

Four tasks in this session were queued against the same repository within minutes of each
other. Their evidence snapshots differ only in when they were taken:

| task | snapshot said | live population |
|---|---|---|
| `feb91eed3b7c` | 41 tips + 572 refs | 682 |
| `03d851526d1e` (this one) | 45 tips + 594 refs | 683 |
| `6642a2ea908c` | 593 refs + worktrees | 635 |
| `b4da5a48b1ee` | 596 refs | 601 |

Reconciling the live source rather than the snapshot, this task's population is
`feb91eed3b7c`'s plus one branch tip created between the two runs. Its 53 RECOVERABLE
items are, to the ref, the same 53. So the honest content of this branch is its ledger.

Recovering them here as well would put the same file contents on two branches under two
filenames, which is exactly the failure the previous reconciliation pass had to unpick:
five sibling branches chained on each other, each carrying the others' commits, none
integrable by the merge train. **No source file is introduced or changed here.**

## Where every item with remaining value actually lives

- `refs/heads/improve/cost-ledger-fail-soft` — the one local-branch-tip recoverable —
  is recovered on `agent/chatgpt-local-reconcile-beethoven-feb91eed3b7c`, cherry-picked
  with `-x` and given the fail-soft tests it shipped without.
- The 52 `refs/orch-rescue/*` recoverables are owned by
  `agent/chatgpt-local-reconcile-beethoven-b4da5a48b1ee`, the sibling whose evidence is
  rescue refs alone.
- The 90 CONFLICTED items each carry their own reason in the ledger rather than being
  summarised away; four are local branch tips whose range diffs no longer apply, and
  forcing them over master would overwrite newer work.

Every one of those dispositions is queryable: the `coordination_tasks` rows written for
this fingerprint carry `source`, `classification`, `disposition` and the owning branch,
so "what happened to ref X" is a query, not an archaeology exercise.

## Provenance

- Nothing deleted, reset, cleaned, popped or moved. The reconcilers read git objects only;
  every `refs/orch-rescue/*` ref and every local branch is intact.
- Enumerated with `tools/reconcile_all_evidence.py` against the live source, not the
  snapshot embedded in the task — the snapshot was already stale when the task ran.
