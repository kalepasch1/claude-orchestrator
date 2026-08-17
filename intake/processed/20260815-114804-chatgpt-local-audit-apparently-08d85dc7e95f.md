PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-08d85dc7e95f
  title: Reconcile local ChatGPT/Codex build evidence for apparently
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
    `08d85dc7e95f6e9c731a1d4a0a81e7c300cd89d7636d79b3ad5ae2c87278a48a`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 1,
        "changes": [
          "knip.config.ts"
        ],
        "changes_digest": "2c60cfabe1125c9a79cadcb377d2e3e9dd93894f71a8cbf9705d6c201e2ddce7",
        "head": "2551a349f622d441a018eac274590857c106d792",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786743497,
        "path": "/Users/kpasch/Documents/apparently-wt/work-20260814"
      }
    ]
