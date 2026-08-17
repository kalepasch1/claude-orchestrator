PROJECT: prediction-markets-institute

- id: chatgpt-local-reconcile-prediction-markets-institute-bc22dbb724c7
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
    `bc22dbb724c7d027ef9607cecc226b12eb7c4714494f669d69eeab7853479ce1`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/rls-regression-ci-gate",
        "change_count": 16,
        "changes": [
          ".aider.chat.history.md",
          ".deploy-canary",
          ".recovery-intent-canary-prediction-markets-institute-20260722.txt",
          ".recovery-intent-canary-prediction-markets-institute-20260727.txt",
          ".recovery-intent-canary-prediction-markets-institute-20260730.txt",
          ".recovery-intent-dropbox-prediction-markets-institute-think-tank-launch-brand-exam-ap-contracts.txt",
          ".recovery-intent-relfix-prediction-markets-institute-07290017.txt",
          ".recovery-intent-shadow-facc0b03-orchestrator_native.txt",
          "app.vue",
          "composables/usePmi.ts",
          "composables/usePmiEntity.ts",
          "composables/usePmiMembership.ts",
          "composables/usePmiPublications.ts",
          "composables/usePmiSupabase.ts",
          "composables/useSeo.ts",
          "vercel.json"
        ],
        "changes_digest": "9c1e501994b2f0b6512bedfcc15766651ec50da41267f69bd8564cde3eef2b35",
        "head": "f9137af7755a484a6709a07d6ba0c1fbe83f7d10",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/rls-regression-ci-gate"
      }
    ]
