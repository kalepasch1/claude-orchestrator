PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-2a509a6cf06c
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
    `2a509a6cf06c881f3a8063d5b4dd03856dbd3706a35ac56d212aeae3bb0b375d`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/cade-mirror-negotiation",
        "change_count": 2,
        "changes": [
          "node_modules",
          "package-lock.json"
        ],
        "changes_digest": "f5098ef7038532f90ff5e1e9be9aacf782532b0061c0f41248f438b7a91d3d9b",
        "head": "47f4a00ca894f8c6ccfd079a0fd17746e320f7c7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786738400,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/cade-mirror-negotiation"
      }
    ]
