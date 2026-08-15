PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-48ada8033590
  title: Reconcile local ChatGPT/Codex build evidence for beethoven
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
    `48ada80335900f35bc5c5838c146e61ae362922b68aca6ff27076a5d37092110`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "master",
        "change_count": 30,
        "changes": [
          "docs/recovery/APPARENTLY_MANUAL_RESTART_CONTINUATION.md",
          "intake/processed/20260807-184025-factory-unblock-cade-adversary-tournaments.md",
          "intake/processed/20260808-183407-factory-unblock-perpetual-compliance-hedge-instrument-fix-ts-errors-.md",
          "intake/processed/20260808-202341-factory-unblock-dropbox-tomorrow-apparently-ploeh-tranche-gating-s-s.md",
          "intake/processed/20260811-173759-0000-v15-trojun-rollout-coordinator-20260811.md",
          "intake/processed/20260811-174428-000-v15-trojun-fleet-rollout-20260811.md",
          "intake/processed/20260811-183744-factory-unblock-recover-missing-branch-perpetual-compliance-hedge-in.md",
          "intake/processed/20260811-193230-orchestrator-development-session-fabric-20260811.md",
          "intake/processed/20260812-001922-operator-improve-compliance-api-auth-tenancy.md",
          "intake/processed/20260812-005435-operator-orchestrator-development-session-fabric-app-embeds-20260812.md",
          "intake/processed/20260812-010435-operator-orchestrator-development-session-fabric-trojun-reroute-20260812.md",
          "intake/processed/20260812-012043-operator-improve-compliance-calibrated-optimization.md",
          "intake/processed/20260812-012309-operator-improve-compliance-durable-event-router.md",
          "intake/processed/20260812-012529-operator-improve-compliance-evidence-vault.md",
          "intake/processed/20260812-012741-operator-improve-compliance-regulatory-ingestion.md",
          "intake/processed/20260812-012936-operator-improve-compliance-scheduling-observability.md",
          "intake/processed/20260812-013137-operator-improve-queue-dirty-checkout-auto-recovery.md",
          "intake/processed/20260812-013309-operator-improve-queue-prevent-darwin-passport-conflicts.md",
          "intake/processed/20260812-013527-operator-improve-queue-prevent-live-runner-merge-conflicts.md",
          "intake/processed/20260812-013735-operator-improve-release-deploy-ui-evidence-closure.md",
          "intake/processed/20260812-013904-operator-improve-runner-credential-capacity-failover.md",
          "intake/processed/20260812-015737-operator-improve-runner-supervisor-single-owner.md",
          "intake/processed/20260812-015737-operator-relfix-v15-apparently-ce3433f9.md",
          "intake/processed/20260812-015737-operator-relfix-v15-pareto-1266ffa3.md",
          "intake/processed/20260812-015737-operator-relfix-v15-predictions-766973c7.md",
          "intake/processed/20260812-015737-operator-relfix-v15-racefeed-f0a41d3a.md",
          "intake/processed/20260812-015737-operator-relfix-v15-smarter-c7599db3.md",
          "intake/processed/20260812-015737-operator-relfix-v15-tomorrow-43b1039e.md",
          "intake/processed/20260812-015904-operator-relfix-v15-trojun-1893305f.md",
          "intake/processed/20260812-020039-operator-relfix-v15-vigil-dcdb561c.md"
        ],
        "changes_digest": "7e991556779e0ee41eea19e41fab3b2dffc7f373c6eb7186b5b471b14a2a1719",
        "head": "8a166025937168fee46e49dda81f9d546221b989",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786496580,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
