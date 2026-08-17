PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-cc4e1a894d39
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
    `cc4e1a894d39059e62f9bd4dd8771e3d65382e39e5d35dd410f04aed7d0f34cb`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "main",
        "change_count": 11,
        "changes": [
          ".aider.chat.history.md",
          ".aider.input.history",
          "IMPLEMENTATION_PROMPT.md",
          "Sustainable_Barks_Strategic_Analysis.docx",
          "app.vue",
          "composables/useAnalytics.ts",
          "composables/useBreadcrumb.ts",
          "composables/useCanonical.ts",
          "composables/useReveal.ts",
          "middleware/portal.ts",
          "tailwind.config.js"
        ],
        "changes_digest": "b5a2e5b64db4310245fd1fb65cde43058a4d2e0d0c1db8068e5be8891a1242b1",
        "head": "0ab0d5bae5c49989871dab31909866f7f4a7bc25",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786668545,
        "path": "/Users/kpasch/Documents/Sustainable_Barks"
      }
    ]
