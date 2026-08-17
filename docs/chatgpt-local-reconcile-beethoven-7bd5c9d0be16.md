# ChatGPT/Codex local evidence reconciliation — beethoven

- **Audit fingerprint:** `7bd5c9d0be16ae945cdbcef3093f941270885f0a553297514e2eee7acacdca1f`
- **Task:** `chatgpt-local-reconcile-beethoven-7bd5c9d0be16`
- **Base:** `origin/master`
- **Ledger:** `.orch/recovery-ledger-7bd5c9d0be16.json` (656 records, 0 UNKNOWN)

## Result

| Classification | Count |
| --- | ---: |
| SUPERSEDED_BY_NEWER | 293 |
| ALREADY_PRESENT | 242 |
| RECOVERABLE_VALUE | 65 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 53 |
| ACTIVE_IN_ANOTHER_TASK | 3 |
| **UNKNOWN** | **0** |

By evidence kind:

| Kind | Items |
| --- | ---: |
| `orchestrator_rescue_refs` | 578 |
| `snapshot:orchestrator_rescue_refs` | 30 |
| `local_only_branch_tips` | 24 |
| `dirty_worktree` | 18 |
| `snapshot:chatgpt_bridge_artifact` | 2 |
| `broken_codex_git_worktree` | 1 |
| `chatgpt_bridge_artifact` | 1 |
| `codex_output_artifact` | 1 |
| `snapshot:broken_codex_git_worktree` | 1 |

All three reconciler stages reported `ok`
(`reconcile_rescue_refs.py`, `reconcile_local_branches.py`,
`reconcile_worktree_evidence.py`), so no item is filed as clean on the strength
of a reconciler that never ran.

## How this run was produced

```sh
python3 tools/extract_task_evidence.py --task-id <id> --out /tmp/evidence-7bd5c9d0be16.json
python3 tools/reconcile_all_evidence.py --base origin/master \
    --fingerprint 7bd5c9d0be16... --repo <repo> --out .orch/recovery-ledger-7bd5c9d0be16.json
node tools/map_snapshot_evidence.mjs --ledger .orch/recovery-ledger-7bd5c9d0be16.json \
    --snapshot /tmp/evidence-7bd5c9d0be16.json --base origin/master
```

Every source path, ref, stash and worktree was treated as read-only. Nothing was
deleted, reset, cleaned, popped or moved: the reconcilers shell out only to
`git for-each-ref`, `cat-file`, `merge-base`, `branch --contains` and `rev-parse`.

## Recoverable value delivered by this task

The reconciliation surfaced a real gap in the toolchain itself, and that is the
code change this task ships.

`tools/reconcile_all_evidence.py` enumerates the **live** evidence and
`tools/map_snapshot_evidence.mjs` folds a task's **snapshot** onto that live
ledger — but nothing in the repo could read the snapshot out of the task prompt.
Prior reconcile runs lifted the array out by hand. That is precisely where a run
drops evidence silently: the snapshot array is embedded in prose and is followed
by more prose, so a naive "first `[` to last `]`" grab either truncates the array
or swallows the trailing text, and **a truncated snapshot is indistinguishable
from a complete one** once it has been parsed — the run then reports zero UNKNOWN
items while having never seen the ones it dropped.

`tools/extract_task_evidence.py` closes that gap:

- a string- and escape-aware bracket scan, so a `]` inside a commit subject
  (`"fix: handle ] in parser"`) does not terminate the array;
- `ExtractionError` on a truncated or malformed snapshot, rather than a partial
  list — a broken snapshot and an empty one must not look the same to the caller,
  because an empty one legitimately means "no evidence" while a broken one means
  "evidence was lost";
- `count_items()` honours the `count` field on digest groups, so a 550-ref
  collection is not mistaken for the 12 refs it sampled.

`tools/test_extract_task_evidence.py` covers all of the above (17 tests),
including the bracket-in-string, escaped-quote, truncation and digest-count cases.

`tools/map_snapshot_evidence.mjs` and its test are carried over unchanged from
`agent/chatgpt-local-reconcile-beethoven-671c267eedf3` — reusing the prior
solution rather than reimplementing it, per the coordination rule. Its 8 tests
pass here.

## Items with remaining value

65 `RECOVERABLE_VALUE` and 53 `CONFLICTED_NEEDS_FOCUSED_TASK` records carry
per-item `disposition` and `evidence` fields in the ledger. Per the task's
coordination rule these are **left in place**: no rescue ref, branch tip or dirty
worktree was touched, and conflicts are recorded for focused follow-up rather
than resolved by overwrite. The ledger is the durable provenance — it is
committed here under the audit fingerprint and mirrored to `coordination_tasks`
as `chatgpt_local_reconcile_ledger` records, one per evidence group.
