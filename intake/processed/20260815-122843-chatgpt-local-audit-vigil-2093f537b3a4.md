PROJECT: vigil

- id: chatgpt-local-reconcile-vigil-2093f537b3a4
  title: Reconcile local ChatGPT/Codex build evidence for vigil
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
    `2093f537b3a452aa3564bb8c595dbe3dd0e7cf66efa77e187fded5fca8ce0ced`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f",
        "change_count": 21,
        "changes": [
          ".aider.chat.history.md",
          ".deploy-canary",
          ".recovery-intent-canary-vigil-20260727-add-update-tests.txt",
          ".recovery-intent-canary-vigil-20260727-locate-owner-module.txt",
          ".recovery-intent-canary-vigil-20260727-run-build-tests.txt",
          ".recovery-intent-canary-vigil-20260728.txt",
          ".recovery-intent-canary-vigil-20260729.txt",
          ".recovery-intent-cont-aaac4e.txt",
          ".recovery-intent-recover-missing-branch-weekly-lint-vigil-add-lint-notification.txt",
          ".recovery-intent-relfix-vigil-07290455.txt",
          ".recovery-intent-relfix-vigil-07290738-fix-gate-failures.txt",
          ".recovery-intent-weekly-lint-vigil.txt",
          "CHATGPT.md",
          "app.vue",
          "composables/apiFetch.ts",
          "composables/useToast.ts",
          "composables/useVigilAuth.ts",
          "middleware/auth.ts",
          "middleware/oauth-callback.global.ts",
          "pnpm-lock.yaml",
          "vercel.json"
        ],
        "changes_digest": "e6eba6a7a1bde6731aab99b6b1f09428cc7bdc97b3c8d4c28dabf115068fe6c8",
        "head": "864828d921540546fcc2a6be2f40d17d3dcd1a6d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/vigil-wt/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f"
      }
    ]
