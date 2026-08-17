PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-30e258bdf0e8
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
    `30e258bdf0e825c83ede1b0de445af3ddd449c19eedbbc5278825c8b4dda98ae`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "orchestrator/dev",
        "change_count": 3,
        "changes": [
          "server/engines/hive-arbitrage-enforcement-hook.ts",
          "server/utils/legal-holds-checker.ts",
          "tests/engines/hive-arbitrage-enforcement-hook.test.ts"
        ],
        "changes_digest": "85f196ae5b4fd93d3b1595abe6f7dba24a37356ad1eb6daab52fa7230d7d54ed",
        "head": "7da7200cf11cb415a5e7c8a629bc92805fa6f2cf",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786488759,
        "path": "/Users/kpasch/Documents/apparently-wt/promote-20260811"
      }
    ]
