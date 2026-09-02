PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-6251390c5da6
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
    `6251390c5da67aa132d54c4e284fb0ebad084f3da3e482271ed941651fc69960`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/rework-secret-tax-return-optimization-cc57fda",
        "change_count": 38,
        "changes_digest": "d00a1976436457b138dbe9d784f0f05ed428dac136b82685de4bbbbcce176bf5",
        "changes_sample": [
          ".aider.chat.history.md",
          ".deploy-canary",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-backlog-batch-sustainable-barks-d4feb77-slice-2-isolate-slice-4-and-slice-5-merg.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-compile-.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-inspect-.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-final-system-validation-final-validation-and-d.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-final-system-validation-resolve-merge-conflict.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-final-system-validation-run-beethoven-tests.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-final-system-validation-run-pricinggridreconst.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-final-system-validation-run-unit-tests.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-final-system-validation-validate-pricinggrid-d.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-final-system-validation-verify-adaptations.txt",
          ".recovery-intent-canary-sustainable-barks-20260708-final-system-validation-verify-library-adaptat.txt",
          ".recovery-intent-canary-sustainable-barks-20260725.txt",
          ".recovery-intent-canary-sustainable-barks-20260726.txt",
          ".recovery-intent-canary-sustainable-barks-20260727.txt",
          ".recovery-intent-chatgpt-local-reconcile-sustainable-barks-65b69fdf9555.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-recover-missing-branch-canary-sustainable-barks-20260708-final-system-validation.txt",
          ".recovery-intent-relfix-sustainable-barks-07220044.txt",
          ".recovery-intent-relfix-sustainable-barks-07251332.txt",
          ".recovery-intent-relfix-sustainable-barks-08011711.txt",
          ".recovery-intent-relfix-sustainable-barks-75b39426be69-fix-runner-emit-task-log.txt",
          ".recovery-intent-remediate-relfix-sustainable-barks-75b39426be69-add-pricing-grid-regression-test.txt",
          ".recovery-intent-rework-legal-recover-missing-branch-fix-sustainable-barks-prod-deploy-sl-93c533f.txt",
          "IMPLEMENTATION_PROMPT.md",
          "Sustainable_Barks_Strategic_Analysis.docx",
          "app.vue",
          "composables/useAnalytics.ts"
        ],
        "changes_total": 38,
        "head": "31725a9700e3ee6506c71c5359d75c978416486b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101320,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rework-secret-tax-return-optimization-cc57fda"
      }
    ]
