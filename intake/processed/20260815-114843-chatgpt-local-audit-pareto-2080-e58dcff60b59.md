PROJECT: pareto-2080

- id: chatgpt-local-reconcile-pareto-2080-e58dcff60b59
  title: Reconcile local ChatGPT/Codex build evidence for pareto-2080
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
    `e58dcff60b598690a1ed452c59a96371d083d92d2bf642d5e259dad179970ece`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/chatgpt-local-reconcile-pareto-2080-a63299895ffc",
        "change_count": 8,
        "changes": [
          "scripts/reconcile-local-evidence.mjs",
          "server/engines/agent-runtime/branch-recovery.ts",
          "server/utils/branchRecovery.js",
          "server/utils/v15/adapter.js",
          "tests/branchRecovery.test.js",
          "tests/engines/branch-recovery.test.ts",
          "tests/experiencePassport.test.js",
          "tests/v15-adapter.test.js"
        ],
        "changes_digest": "e3aeddb8c3a79a8ddae6d17ad3c5494220f11c034af4535bda09fe32a8c0c6f2",
        "head": "5b56e41625e08ce5863dfbdf004647062a06f450",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786743161,
        "path": "/Users/kpasch/Documents/pareto/2080-wt/a63299895ffc"
      }
    ]
