PROJECT: illuminati

- id: chatgpt-local-reconcile-illuminati-d875792b92fa
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
    `d875792b92fa6061874ab92f4810de22458e2f4893888e0878936f89d0700cc3`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 182,
        "changes_digest": "d4e0bb72d5d0bdaa0fe64837a513aa9dd0bbbf6a46b31c39eba8d8d77372c15b",
        "changes_sample": [
          "\"test-results/journeys-J1-\\342\\200\\223-sign-in-page-e9a93-with-correct-title-and-form-chromium/error-context.md\"",
          "\"test-results/journeys-J2-\\342\\200\\223-magic-link-send-shows-email-confirmation-chromium/error-context.md\"",
          "\"test-results/journeys-J3-\\342\\200\\223-OTP-request-carries-the-email-the-user-typed-chromium/error-context.md\"",
          "\"test-results/journeys-J4-\\342\\200\\223-portfolio-health-page-loads-chromium/error-context.md\"",
          "\"test-results/journeys-J5-\\342\\200\\223-fleet-admin-page-loads-chromium/error-context.md\"",
          "\"test-results/journeys-J6-\\342\\200\\223-growth-OS-oversight-page-loads-chromium/error-context.md\"",
          ".aider.input.history",
          ".recovery-intent-dropbox-cross-app-hivemind-federation-one-market-shaped-intelligence-contracts.txt",
          "CLAUDE.md",
          "README.md",
          "SPEC.md",
          "app.vue",
          "app/lib/one-apparently/contracts.ts",
          "cli/src/client.ts",
          "cli/src/index.ts",
          "components/CadeOperatingSystem.vue",
          "components/ConnectorOptimizationPanel.vue",
          "components/ConnectorUnlockGraph.vue",
          "components/ConstitutionalAutonomy.vue",
          "components/ExecutionConstitution.vue",
          "components/ExperienceLayer.vue",
          "components/HivemindEconomy.vue",
          "components/HivemindGovernance.vue",
          "components/IlluminatiLanding.vue",
          "components/IlluminatiWordmark.vue",
          "components/LegoraLanding.vue",
          "components/MadeusLogo.vue",
          "components/MadeusMark.vue",
          "components/OrganizationPassport.vue",
          "components/PortfolioSafeSimulator.vue"
        ],
        "changes_total": 100,
        "head": "5bbed69bdb992608a06294883e4a8658635b455e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786492020,
        "path": "/private/tmp/illuminati-release-8FeZUh"
      }
    ]
