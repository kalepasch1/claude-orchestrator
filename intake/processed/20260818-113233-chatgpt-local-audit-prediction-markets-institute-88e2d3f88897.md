PROJECT: prediction-markets-institute

- id: chatgpt-local-reconcile-prediction-markets-institute-88e2d3f88897
  title: Reconcile local ChatGPT/Codex build evidence for prediction-markets-institute
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
    `88e2d3f8889762141739cde66539205f4b72b7a69c68828355c0deb8c4cf88f6`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "main",
        "change_count": 1,
        "changes": [
          "public/og.png"
        ],
        "changes_digest": "6c4b072d43629f3b71f090155c2eb8648b01188039b4aabeea71c3dc92dc429d",
        "head": "6e686b6cbecaa825664a1c4b7101949223a61c69",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787026314,
        "path": "/Users/kpasch/Documents/PMA/prediction-markets-institute"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/PMA/prediction-markets-institute",
        "routing": "prediction-markets-institute"
      }
    ]
