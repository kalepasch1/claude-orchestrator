PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-b86a58bad502
  title: Reconcile local ChatGPT/Codex build evidence for racefeed
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
    `b86a58bad50231976968ba1e76aeed3d3f8edafeff58ebbbcc4fba4a47416c5f`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/cade-mirror-negotiation",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739317,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cade-mirror-negotiation"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739322,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/session-proof-of-work"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739311,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/smarter-5-95"
      }
    ]
