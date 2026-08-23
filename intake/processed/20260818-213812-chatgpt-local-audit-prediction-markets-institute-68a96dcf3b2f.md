PROJECT: prediction-markets-institute

- id: chatgpt-local-reconcile-prediction-markets-institute-68a96dcf3b2f
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
    `68a96dcf3b2f26e2a44a2f7d8f3ac05d62524a5e9807269d023bd4dc5a0e3b0b`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "main",
        "change_count": 2,
        "changes": [
          ".convention-rules.json",
          "package-lock.json"
        ],
        "changes_digest": "cb81cfafc14219c8cfa2e91d47cdcbaf5fa5cb97065ca6dfa45c5a52a7fcb3a8",
        "head": "6d7f4cf9a09eda37234341e64888b615c57825c9",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787066268,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi"
      }
    ]
