PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-da7954fc9f0e
  title: Reconcile local ChatGPT/Codex build evidence for sustainable-barks
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
    `da7954fc9f0ed860363e385dcbabc28626c67846326f7105af47bdc83d3ec6e8`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
        "head": "0ab0d5bae5c49989871dab31909866f7f4a7bc25",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787102944,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/orch-config-consumption"
      }
    ]
