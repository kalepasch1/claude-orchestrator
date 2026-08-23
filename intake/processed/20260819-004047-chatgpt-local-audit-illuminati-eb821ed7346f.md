PROJECT: illuminati

- id: chatgpt-local-reconcile-illuminati-eb821ed7346f
  title: Reconcile local ChatGPT/Codex build evidence for illuminati
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
    `eb821ed7346f673f6610799cace2937aaf5da5cbca8b02bd02b08287a2cc01cc`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/contracts-smarter",
        "change_count": 53,
        "changes_digest": "bb6728ee5b51e56e1b43e8edb08e8be80c8aa43f8786ea6ae053e493d830f6b7",
        "changes_sample": [
          ".aider.chat.history.md",
          "CHATGPT.md",
          "app.vue",
          "app/lib/one-apparently/contracts.ts",
          "composables/useAdaptiveProficiency.ts",
          "composables/useCascadeMetrics.ts",
          "composables/useCascadeStream.ts",
          "composables/useDeploymentHistory.ts",
          "composables/useExperienceTelemetry.ts",
          "composables/useFleetWebSocket.ts",
          "composables/useJourneyFriction.ts",
          "composables/useOrchestratorSnapshot.ts",
          "composables/usePersistentProjectContext.ts",
          "composables/usePreActionGuidance.ts",
          "composables/useRealtimeTable.ts",
          "composables/useReviewMode.ts",
          "composables/useTerminalConnection.ts",
          "composables/useTerminalState.ts",
          "config/businessCapabilities.ts",
          "config/connectors.ts",
          "config/designCapabilities.ts",
          "config/experience-contracts.json",
          "config/journey-contracts.json",
          "config/legalContracts.ts",
          "config/navigation.ts",
          "config/orchestratorCapabilities.ts",
          "config/previewTargets.ts",
          "contracts/HEDGE-BRIDGE.md",
          "contracts/README.md",
          "contracts/migrations/stub_0001_standing_opportunities.sql"
        ],
        "changes_total": 53,
        "head": "f285e72ba24cd7e9e7d9bfe915505bc350ab9206",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/Trojun-wt/contracts-smarter"
      },
      {
        "branch": "agent/counterfactual-replay",
        "change_count": 53,
        "changes_digest": "bb6728ee5b51e56e1b43e8edb08e8be80c8aa43f8786ea6ae053e493d830f6b7",
        "changes_sample": [
          ".aider.chat.history.md",
          "CHATGPT.md",
          "app.vue",
          "app/lib/one-apparently/contracts.ts",
          "composables/useAdaptiveProficiency.ts",
          "composables/useCascadeMetrics.ts",
          "composables/useCascadeStream.ts",
          "composables/useDeploymentHistory.ts",
          "composables/useExperienceTelemetry.ts",
          "composables/useFleetWebSocket.ts",
          "composables/useJourneyFriction.ts",
          "composables/useOrchestratorSnapshot.ts",
          "composables/usePersistentProjectContext.ts",
          "composables/usePreActionGuidance.ts",
          "composables/useRealtimeTable.ts",
          "composables/useReviewMode.ts",
          "composables/useTerminalConnection.ts",
          "composables/useTerminalState.ts",
          "config/businessCapabilities.ts",
          "config/connectors.ts",
          "config/designCapabilities.ts",
          "config/experience-contracts.json",
          "config/journey-contracts.json",
          "config/legalContracts.ts",
          "config/navigation.ts",
          "config/orchestratorCapabilities.ts",
          "config/previewTargets.ts",
          "contracts/HEDGE-BRIDGE.md",
          "contracts/README.md",
          "contracts/migrations/stub_0001_standing_opportunities.sql"
        ],
        "changes_total": 53,
        "head": "f285e72ba24cd7e9e7d9bfe915505bc350ab9206",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/Trojun-wt/counterfactual-replay"
      }
    ]
