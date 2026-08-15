PROJECT: illuminati

- id: chatgpt-local-reconcile-illuminati-7438c8c9e567
  title: Reconcile local ChatGPT/Codex build evidence for illuminati
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
    `7438c8c9e567690ce960b226d664c62061e47960cb3ff827c98b1745d7aaab01`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "fix/fail-closed-supabase-config-20260812",
        "change_count": 3,
        "changes": [
          "package-lock.json",
          "package.json",
          "server/data/verdict-cards.json"
        ],
        "changes_digest": "9cf9f33c7bef2139c82af05eceb6b1e822951bc6f80dda5aa05f43a7539f17c5",
        "head": "ad653f7f91f9ab320002a59befb0d9f7ba5ca9d1",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786492634,
        "path": "/Users/kpasch/Documents/illuminati"
      }
    ]
