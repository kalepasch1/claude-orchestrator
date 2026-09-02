PROJECT: apparently-law

- id: chatgpt-local-reconcile-apparently-law-7da4852c4e50
  title: Reconcile local ChatGPT/Codex build evidence for apparently-law
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
    `7da4852c4e5047994223756361676f33b5e47bd8565667806cb9ce4376585b9d`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/orch-config-consumption",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "9b3107c6c81e8aa22abcb9d768afd0e2beeabdf2",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103086,
        "path": "/Users/kpasch/Documents/apparently-law-wt/orch-config-consumption"
      },
      {
        "branch": "agent/rework-secret-mutual-credit-33b3a46",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "9b3107c6c81e8aa22abcb9d768afd0e2beeabdf2",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103096,
        "path": "/Users/kpasch/Documents/apparently-law-wt/rework-secret-mutual-credit-33b3a46"
      },
      {
        "branch": "agent/rework-secret-tax-return-optimization-cc57fda",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "9b3107c6c81e8aa22abcb9d768afd0e2beeabdf2",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103091,
        "path": "/Users/kpasch/Documents/apparently-law-wt/rework-secret-tax-return-optimization-cc57fda"
      }
    ]
