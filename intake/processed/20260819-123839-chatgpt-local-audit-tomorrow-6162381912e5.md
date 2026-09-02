PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-6162381912e5
  title: Reconcile local ChatGPT/Codex build evidence for tomorrow
  material: yes
  depends: []
  proof: every evidence item is classified and all still-useful absent code is durably queued or integrated
  prompt: |
    Reconcile the local ChatGPT/Codex build evidence below without destroying or overwriting it.

    This is a recovery-and-consideration task, not permission to prefer legacy code over current code.
    Treat every source path, stash, rescue ref, and worktree as read-only. Compare each item against
    the current default branch, remote branches, merged history, and live orchestrator tasks. Classify
    each item as ALREADY_PRESENT, SUPERSEDED_BY_NEWER, ACTIVE_IN_ANOTHER_TASK, RECOVERABLE_VALUE, or
    CONFLICTED_NEEDS_FOCUSED_TASK. The newest/most complete implementation wins.

    For RECOVERABLE_VALUE, work only in a newly allocated isolated worktree, apply the minimum coherent
    diff, run relevant tests, and deliver through the normal agent branch + merge train. For conflicts,
    queue a focused follow-up rather than forcing an overwrite. Do not delete, reset, clean, pop, or move
    the evidence source. Do not duplicate work already represented by a live task or remote branch.

    Write one `coordination_tasks` recovery-ledger record per evidence item using audit fingerprint
    `6162381912e545c6882fa516d3b5a8e95484198d702930b54a9a40ee1c8ee408`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/deployfix-darwn-vercel-1783343439",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "aa31ea3c622d617e1a22f07a891faec82a5209c6",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787100364,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/deployfix-darwn-vercel-1783343439"
      },
      {
        "branch": "agent/rework-secret-a2a-endpoint-0743615",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "aa31ea3c622d617e1a22f07a891faec82a5209c6",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787100428,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/rework-secret-a2a-endpoint-0743615"
      },
      {
        "branch": "agent/rework-secret-attested-outcomes-9563340",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "aa31ea3c622d617e1a22f07a891faec82a5209c6",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787100496,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/rework-secret-attested-outcomes-9563340"
      }
    ]
