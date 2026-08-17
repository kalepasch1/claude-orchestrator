# ChatGPT/Codex local build-evidence reconciliation — beethoven (rescue refs, second pass)

- Audit fingerprint: `9b427697d13fd724cc0be9acb2d6ca991da66fa2d0249c9632c16dc1c08d00ab`
- Task: `chatgpt-local-reconcile-beethoven-9b427697d13f`
- Evidence source: `/Users/kpasch/Documents/beethoven/claude-orchestrator` — `refs/orch-rescue/*` (read-only; nothing deleted, reset, cleaned, popped or moved)
- Refs enumerated from the live source: **577**
- UNKNOWN items: **0**
- Machine-readable ledger: `.orch/recovery-ledger-9b427697d13f.json`

## Classification summary

| Classification | Count |
|---|---|
| ALREADY_PRESENT | 112 |
| SUPERSEDED_BY_NEWER | 240 |
| ACTIVE_IN_ANOTHER_TASK | 66 |
| RECOVERABLE_VALUE | 0 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 159 |

## Nothing new to recover, and that is the finding

This snapshot (554 rescue refs) is the same population `chatgpt-local-reconcile-beethoven-8d0702cbd5aa`
enumerated at 577. Absence was therefore computed against `origin/master` AND all three sibling
recovery branches from this session, so **63 refs come back ACTIVE_IN_ANOTHER_TASK** instead of
re-recovering files those passes already took.

This branch is based on the sibling chain, so every earlier recovery is carried forward and this
commit adds only the ledger. **No source file is introduced or changed.**

## A classifier bug worth recording

The first pass over this evidence reported 12 refs as RECOVERABLE_VALUE. Six of the paths behind
that number did not exist:

```
PROMPT-pareto-apparently-treasury.md      PROMPT-tomorrow-credit-rails-v2.md
PROMPT-ILLUMINATI-ABSORPTION.md           PROMPT-SMARTER-CAPABILITY-BRIDGE.md
runner/test_economic_scheduler_revenue.py runner/tests/test_economic_scheduler_revenue.py
```

They appear in `git diff --name-only base...ref` and are absent from `git ls-tree base`, which is
exactly the shape a recoverable file has. But in a three-dot diff a path can also appear because it
was DELETED on the ref side relative to the merge base — present in neither the base nor the ref.
Replaying such a path recreates nothing; `git checkout <ref> -- <path>` fails with
`pathspec did not match any file(s) known to git`.

**Absence from the base is not the test. Presence in the ref tree is.** The ledger records the
corrected classification, and these six are marked SUPERSEDED_BY_NEWER with the reason stated
rather than left looking like value that was dropped on the floor.

A seventh entry, `Updated show_greeting.py`, is a diff-header line captured as a filename by the
same class of malformed patch. It is not a file either.

## What remains queued

The other refs that looked recoverable carry only tests the `8d0702cbd5aa` pass deliberately
deferred (they assert against newer versions of `bandit`, `priority_queue`, `merge_train`,
`release_train` and `reconcile-evidence.mjs`). They are covered by
`beethoven-reconcile-followup-deferred-tests-newer-module-versions`.

159 refs modify paths `origin/master` already carries and are covered by
`beethoven-reconcile-followup-222-conflicted-rescue-refs`. No duplicate follow-up was created.

## Provenance

- ACTIVE_IN_ANOTHER_TASK -> the three sibling branches from this session, all pushed.
- CONFLICTED / deferred -> existing queued tasks, named above.
- Every `refs/orch-rescue/*` ref remains intact in the local repository.

