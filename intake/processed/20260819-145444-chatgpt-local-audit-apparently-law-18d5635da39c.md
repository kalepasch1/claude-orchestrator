PROJECT: apparently-law

- id: chatgpt-local-reconcile-apparently-law-18d5635da39c
  title: Reconcile local ChatGPT/Codex build evidence for apparently-law
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
    `18d5635da39c3bbd5b644e82895ed3f03543f08bddc996d137cb481ed7b5caa6`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/rework-secret-demand-exchange-endpoint-ac4d429",
        "change_count": 179,
        "changes_digest": "6d172b0b4119828ca64c6f1764f96004b4851f42b526c4c0912b484b91fbf061",
        "changes_sample": [
          "app/app.vue",
          "app/assets/css/main.css",
          "app/assets/css/sister.css",
          "app/components/CreateMatterModal.vue",
          "app/components/CreateTimeEntryModal.vue",
          "app/components/CtaBand.vue",
          "app/components/DisclosureNote.vue",
          "app/components/FeatureCard.vue",
          "app/components/FractionalGCCalculator.vue",
          "app/components/Icon.vue",
          "app/components/LegalSpendModel.vue",
          "app/components/MatterCard.vue",
          "app/components/MemoReadinessCheck.vue",
          "app/components/PageHero.vue",
          "app/components/PracticeEconomicsModel.vue",
          "app/components/RiskStorefrontTeaser.vue",
          "app/components/SectionHead.vue",
          "app/components/SiteFooter.vue",
          "app/components/SiteHeader.vue",
          "app/components/SiteWordmark.vue",
          "app/components/StatCard.vue",
          "app/components/SweepsMemoAudit.vue",
          "app/components/TankSharkApplication.vue",
          "app/components/TimeEntryItem.vue",
          "app/components/VideoCard.vue",
          "app/components/VideoHub.vue",
          "app/composables/useContextVideo.ts",
          "app/composables/usePageSeo.ts",
          "app/composables/usePractitionerOs.ts",
          "app/error.vue"
        ],
        "changes_total": 100,
        "head": "9b3107c6c81e8aa22abcb9d768afd0e2beeabdf2",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787100834,
        "path": "/Users/kpasch/Documents/apparently-law-wt/rework-secret-demand-exchange-endpoint-ac4d429"
      },
      {
        "branch": "integrate/regmap-sister",
        "change_count": 1,
        "changes": [
          ".convention-rules.json"
        ],
        "changes_digest": "52b17955319c454214d9c65fe286f7f8abc398c6d3cdba375264c0f60a3f5e8e",
        "head": "d266e47237c5891dee5d7d50d5291e37639533a6",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786955452,
        "path": "/Users/kpasch/Documents/apparently-law"
      },
      {
        "branch": "integrate/regmap-final",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "3f260d71126b08343a1bdab87eb9aa5b7531d37d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787062779,
        "path": "/Users/kpasch/Documents/apparently-law-wt/regmap-final"
      }
    ]
