PROJECT: pareto-2080

- id: chatgpt-local-reconcile-pareto-2080-c4c56c9ead84
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
    `c4c56c9ead84f02a2fbb19768101c49f9d2f789198725ee6cfae303fb71c96e6`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 1262,
        "changes_digest": "eb3a897175f290b3a827aa1ddb5c97a3642e4bb30a385e6d44cb2470f03a15b9",
        "changes_sample": [
          ".commit-message",
          ".commit_msg",
          ".deploy-canary",
          ".gitignore.bak",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-into-smaller-indepe.txt",
          ".recovery-intent-backlog-batch-pareto-2080-1259f9c.txt",
          ".recovery-intent-backlog-batch-pareto-2080-5643cef-buildfail-patch-template.txt",
          ".recovery-intent-backlog-batch-pareto-2080-5643cef-locate-owner-module.txt",
          ".recovery-intent-backlog-batch-pareto-2080-a02d210-apply-patch-template.txt",
          ".recovery-intent-backlog-batch-pareto-2080-c20f077-slice-2-categorize-stale-backlog-items-apply-c.txt",
          ".recovery-intent-backlog-batch-pareto-2080-c20f077-slice-2-categorize-stale-backlog-items-validat.txt",
          ".recovery-intent-backlog-batch-pareto-2080-c20f077-slice-2-create-remediation-for-complex-stale-i.txt",
          ".recovery-intent-backlog-batch-pareto-2080-c20f077-slice-5-identify-pricing-grid-build-duplicates.txt",
          ".recovery-intent-backlog-batch-pareto-2080-f133ba9.txt",
          ".recovery-intent-canary-pareto-2080-20260722.txt",
          ".recovery-intent-canary-pareto-2080-20260726-update-build-script.txt",
          ".recovery-intent-canary-pareto-2080-20260727.txt",
          ".recovery-intent-canary-pareto-2080-20260730.txt",
          ".recovery-intent-chatgpt-local-reconcile-pareto-2080-4538cb90f476.txt",
          ".recovery-intent-chatgpt-local-reconcile-pareto-2080-9b4ddc1eb702.txt",
          ".recovery-intent-chatgpt-local-reconcile-pareto-2080-e191061d22ff.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-dropbox-merge-train-throughput-recovery-drive-581-skipped-to-merged--contracts.txt",
          ".recovery-intent-dropbox-wave-f-universal-coverage-doctrine-kill-the-silence-reads-as-contracts.txt",
          ".recovery-intent-fix-remaining-engine-tests-fix-charitable-bunching-and-asset-locati-correct-asse.txt",
          ".recovery-intent-fix-remaining-engine-tests-fix-roth-conversion-and-estimated-tax-estimated-tax-c.txt",
          ".recovery-intent-fix-remaining-engine-tests-fix-roth-conversion-and-estimated-tax-roth-tax-consta.txt",
          ".recovery-intent-gate-esm-cjs-guard-document-esm-only-policy-locate-esm-section.txt",
          ".recovery-intent-gate-esm-cjs-guard-document-esm-only-policy.txt"
        ],
        "changes_total": 100,
        "head": "",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/pareto/2080-wt/rework-secret-a2a-endpoint-0743615"
      }
    ]
