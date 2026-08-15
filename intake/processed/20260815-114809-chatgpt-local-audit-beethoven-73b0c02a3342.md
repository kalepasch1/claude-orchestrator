PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-73b0c02a3342
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
    `73b0c02a3342da970c527e3f950bb2ebdb5553e8542bf09d434b8c14253aad7c`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "master",
        "change_count": 57,
        "changes_digest": "a855dd4ab45c05f45094695c3bae88dddb6efcfb57d4efda8d7f87ccb27d0307",
        "changes_sample": [
          "docs/decisions/ADR-2026-08-08-5b3f0660-88c2-43ff-8928-5d85aaf023ef.md",
          "docs/decisions/ADR-2026-08-08-8096ccb3-ed1e-417e-93ee-4cce4e0a2948.md",
          "docs/decisions/ADR-2026-08-08-business-model-check-regulatory-dropbox-tomorrow-foulkon-hed.md",
          "docs/decisions/ADR-2026-08-08-e4a29eee-59fe-4409-a9a0-cffe9c0cb53c.md",
          "docs/decisions/ADR-2026-08-08-f4c5fb8c-98c8-4784-a2d1-7db5d021fa54.md",
          "docs/decisions/ADR-2026-08-08-f879c3d4-d1bc-446f-ba0c-c22192ed3756.md",
          "docs/decisions/ADR-2026-08-11-business-model-check-regulatory-p1-product-integration-gaps-.md",
          "docs/decisions/ADR-2026-08-11-business-model-check-regulatory-part9-foresight-shadow-packs.md",
          "docs/decisions/ADR-2026-08-13-10f761a4-af79-4c51-8750-683bc2dc3257.md",
          "docs/decisions/ADR-2026-08-13-5cf16310-1131-472a-b470-ef38377957a5.md",
          "docs/decisions/ADR-2026-08-13-72fcfbef-fd9c-4319-a5c3-463658e43515.md",
          "docs/decisions/ADR-2026-08-13-bcbf1013-b0e4-49c7-a9a4-35e6ec51883a.md",
          "docs/decisions/ADR-2026-08-13-bdec4843-2077-4375-8791-49165a0aafb0.md",
          "docs/decisions/ADR-2026-08-14-90324165-ee8b-4f8f-a493-1908200c236e.md",
          "docs/decisions/ADR-2026-08-14-c2cb396d-3d4e-4278-822a-e8ce07941b52.md",
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
          "intake/processed/20260812-012741-operator-improve-compliance-regulatory-ingestion.md"
        ],
        "changes_total": 57,
        "head": "e4a47d9ad0e286d36401ef90b186badfeea02342",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786737511,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
