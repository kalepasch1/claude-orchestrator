PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-adb65fbcd541
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
    `adb65fbcd541a03d195e3fcc33e386eb6f573aeda5f6a0809278e7e6c02a2685`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "landing-revamp-20260811",
        "change_count": 69,
        "changes_digest": "3201856fdc7a96ef016e60032a528d0022eda0ceb5fd315e8da8c4a62ec7c5da",
        "changes_sample": [
          ".convention-rules.json",
          "_transform_light.py.stale",
          "_transform_light2.py.stale",
          "_transform_light3.py.stale",
          "components/warRoom/IntelligencePanel.vue",
          "composables/useIntelligencePanel.ts",
          "composables/useMoveAnalysis.ts",
          "composables/useSwapCompliance.ts",
          "composables/warRoomIntel.ts",
          "docs/DESIGN-ideas-exchange-20260817.md",
          "package-lock.json",
          "pages/app/admin/loop-status.vue",
          "pages/app/agents/constitution.vue",
          "pages/app/capital-cockpit/index.vue",
          "pages/app/capital-liberation/cross-segment.vue",
          "pages/app/compliance/index.vue",
          "pages/app/intelligence/pricing.vue",
          "pages/app/otc/bank/economics.vue",
          "pages/app/otc/gaming/console.vue",
          "pages/app/protect/cost-lock.vue",
          "pages/app/settlement/dlt-dashboard.vue",
          "pages/app/settlement/explorer.vue",
          "pages/firm/negotiations/[id]/war-room.vue",
          "prisma/schema.prisma",
          "server/api/admin/run-backtest.post.ts",
          "server/api/analysis/correlation-bundles.get.ts",
          "server/api/apparently/cade/predict-counterparty.ts",
          "server/api/cade/analyze-move.post.ts",
          "server/api/compliance/audit-log.get.ts",
          "server/api/cron/bot27-optimizer.get.ts"
        ],
        "changes_total": 69,
        "head": "86e119f06ec004a85edb56308570729a13b169ac",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787109393,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow"
      }
    ]
