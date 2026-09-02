PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-25a6310927a5
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
    `25a6310927a5900826831f1213e5da8fa7758cb0b0c43edcd06e376d6d6ca0b8`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "orchestrator/dev",
        "change_count": 5,
        "changes": [
          ".convention-rules.json",
          "_transform_light.py.stale",
          "_transform_light2.py.stale",
          "_transform_light3.py.stale",
          "tomorrow-wt/landing-concise/"
        ],
        "changes_digest": "e82f52c40eafa2316965c266769677c21847ecdf2e8031b0c03cccdceae6ceab",
        "head": "ee8079157a6272d96208e0c7cbb921071a36e743",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787109393,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow"
      }
    ]
