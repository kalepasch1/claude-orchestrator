PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-6c2623872edc
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
    `6c2623872edc9631a7ed9983888af929b351faec5601db2eaff7eba33e81ed0c`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/cont-5f9e0e",
        "change_count": 222,
        "changes_digest": "67205e9be4c5f791530199af2b9b6bc2f9c93e485129fb8b66ee44b0e5f26c00",
        "changes_sample": [
          ".deploy-canary",
          ".husky/pre-commit",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-backlog-batch-tomorrow-4210042.txt",
          ".recovery-intent-backlog-batch-tomorrow-c44138a.txt",
          ".recovery-intent-backlog-batch-tomorrow-d8f0b3a.txt",
          ".recovery-intent-chatgpt-local-reconcile-tomorrow-1959809d4e74.txt",
          ".recovery-intent-cont-97381e.txt",
          ".recovery-intent-contingent-identity-split-contingentidentity-slice-5.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-1-upd.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-4-imp.txt",
          ".recovery-intent-dropbox-economic-scheduler-revenue-revenue-focused-task-prioritizati-group-5-imp.txt",
          ".recovery-intent-dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-master-task.txt",
          ".recovery-intent-dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-notes-luxur.txt",
          ".recovery-intent-dropbox-pareto-2080-luxury-consigliere-repositioning-5m-ecp-passport-notes-stand.txt",
          ".recovery-intent-dropbox-portfolio-doctrine-shared-services-x-items-slice-1.txt",
          ".recovery-intent-factory-unblock-chatgpt-local-reconcile-tomorrow-41fc0d56c6e3.txt",
          ".recovery-intent-qafix-tomorrow-07062319-slice-4-slice-4-implement-core-adapted-logic-patch-templ.txt",
          ".recovery-intent-recover-missing-branch-determinations-engine-spec-slice-2.txt",
          ".recovery-intent-recover-missing-branch-merge-legacy-fix-vue-css.txt",
          ".recovery-intent-recover-missing-branch-perpetual-compliance-hedge-instrument-restore-npm-deps.txt",
          ".recovery-intent-recover-missing-branch-sik-verification.txt",
          ".recovery-intent-remediate-qafix-tomorrow-07062319-slice-1-slice-5-locateexistingownermodulefunct.txt",
          ".recovery-intent-remediate-spec-reconcile-3fb58a.txt",
          ".tsc-error-baseline",
          "AUTH_NOTES.md",
          "BACKLOG-BATCH-7CE8BFB.md",
          "COMPLETENESS_CREDIT_50X_OPPORTUNITIES.md",
          "COMPLETENESS_CREDIT_LAUNCH_REMEDIATIONS.md"
        ],
        "changes_total": 100,
        "head": "aa31ea3c622d617e1a22f07a891faec82a5209c6",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787104442,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/cont-5f9e0e"
      }
    ]
