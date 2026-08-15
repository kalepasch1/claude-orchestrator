PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-f488256b7d2c
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
    `f488256b7d2c37e32c842bc5a026d0bf38c5a730e8bb80fab32738b6eff37c9f`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "landing-revamp-20260811",
        "change_count": 58,
        "changes_digest": "ae5eb49f3f23af3f0a6ce4b77fd69607c8ca752ac37538f0b4ec36f171549175",
        "changes_sample": [
          "_to_delete/HEAD.lock.5",
          "articles/_archive/TOPIC-LEDGER.md",
          "articles/_archive/run-reports/2026-08-11.md",
          "articles/medium/2026-08-11_the-morning-the-exchange-unwound-the-market.md",
          "articles/medium/2026-08-11_the-pitch-and-the-pennant.md",
          "components/v2/AppSidebar.vue",
          "composables/useConvictionIntel.ts",
          "composables/useGamification.ts",
          "composables/useMemberCredit.ts",
          "composables/usePositionManager.ts",
          "composables/useUserRole.ts",
          "pages/app/benefits/index.vue",
          "pages/app/board/index.vue",
          "pages/app/intelligence/index.vue",
          "pages/app/leverage/index.vue",
          "pages/app/positions/index.vue",
          "pages/login.vue",
          "prisma/migrations/20260808_alter_position_derivative_columns/migration.sql",
          "prisma/migrations/20260808_gamification_tables/migration.sql",
          "prisma/migrations/20260808_positions_credit_intel/migration.sql",
          "scripts/reconcile-evidence.mjs",
          "server/api/v2/benefits/events/[id]/rsvp.post.ts",
          "server/api/v2/credit/draw.post.ts",
          "server/api/v2/credit/free-taste.get.ts",
          "server/api/v2/credit/free-taste/claim.post.ts",
          "server/api/v2/credit/perks.get.ts",
          "server/api/v2/credit/referral.get.ts",
          "server/api/v2/credit/referral/link.post.ts",
          "server/api/v2/credit/summary.get.ts",
          "server/api/v2/gamification/activity.post.ts"
        ],
        "changes_total": 58,
        "head": "a933b66597175ac3b323c8d5cce75614b171e063",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786517451,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow"
      },
      {
        "branch": "agent/chatgpt-local-reconcile-tomorrow-8ce35eb9ae43",
        "change_count": 2,
        "changes": [
          "docs/recovery-ledger/428d9cdff1e1.json",
          "docs/recovery-ledger/8ce35eb9ae43.json"
        ],
        "changes_digest": "5ceba379e9ab4445da04e7dac35f3e24f1ce6f66b35161c8f46f64bbd2a1f1f0",
        "head": "2f71d4e5af8696d3a78f790108b983f7e36009a6",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786519835,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/reconcile-batch4"
      }
    ]
