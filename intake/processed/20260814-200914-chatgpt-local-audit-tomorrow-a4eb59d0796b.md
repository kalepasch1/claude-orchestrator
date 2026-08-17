PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-a4eb59d0796b
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
    `a4eb59d0796b51e9b2b8f80189f715acd08e5c5c9a771ed6de4ce273d9a6e77f`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 1,
        "changes": [
          "packages/curation-core/node_modules/.vite/vitest/da39a3ee5e6b4b0d3255bfef95601890afd80709/results.json"
        ],
        "changes_digest": "57f90ec4d4c0896116a6af3cb2ad565771de743f6f1f96c35b413e7db8bbe304",
        "head": "a933b66597175ac3b323c8d5cce75614b171e063",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/6973da69fb225e176b92"
      },
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
        "branch": "DETACHED",
        "change_count": 1,
        "changes": [
          "server/api/v2/intelligence/index/index.get.ts"
        ],
        "changes_digest": "bb7eba707a822afd1731977c5b07b9264ce2ea1d48a7d1d892ac7cbdda50ab0f",
        "head": "71ed141dba226a8bb5b1c6b6454ebbee908b30d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786578639,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/chatgpt-local-reconcile-x2"
      },
      {
        "count": 40,
        "items_digest": "419a54df1a7f2e076be079fc635b2f7c62b0a07fdf31559ce09e58f27fe75796",
        "items_sample": [
          {
            "created_at": 1784742125,
            "ref": "stash@{0}",
            "sha": "2cd78e17c8a365dc124e0a50741399080aa28925",
            "subject": "WIP on main: e683890f99 Include runtime export guard in Vercel builds"
          },
          {
            "created_at": 1784741910,
            "ref": "stash@{1}",
            "sha": "dcffee0b2d580d223d8122efab145982372d6dee",
            "subject": "WIP on main: 114a6c081a fix(build #24): add 144 stub exports across 22 files \u2014 bulk MISSING_EXPORT fix"
          },
          {
            "created_at": 1784739036,
            "ref": "stash@{2}",
            "sha": "8e6dedd47f4ed7975bffbd66795d3865121899e1",
            "subject": "WIP on main: 9ff44d1aea fix(build): add missing onAutoSkipApproved/onAutoSkipRejected exports to autoSkipGate.ts"
          },
          {
            "created_at": 1784739023,
            "ref": "stash@{3}",
            "sha": "0393f53c77e20af388edb218def236236f6e710f",
            "subject": "On main: all changes before rebase"
          },
          {
            "created_at": 1784739016,
            "ref": "stash@{4}",
            "sha": "614cfe6fe203351090a757da516c43f63defd1d9",
            "subject": "On main: node_modules changes before rebase"
          },
          {
            "created_at": 1784739011,
            "ref": "stash@{5}",
            "sha": "a6c983dc4f395f1b92b848b73b1b432e27987b4f",
            "subject": "WIP on main: 9ff44d1aea fix(build): add missing onAutoSkipApproved/onAutoSkipRejected exports to autoSkipGate.ts"
          },
          {
            "created_at": 1784738957,
            "ref": "stash@{6}",
            "sha": "117194ad9c737729f2a22800411aab7a72c8c23c",
            "subject": "WIP on main: 9ff44d1aea fix(build): add missing onAutoSkipApproved/onAutoSkipRejected exports to autoSkipGate.ts"
          },
          {
            "created_at": 1784699533,
            "ref": "stash@{7}",
            "sha": "9bcab60f554cf0bac007b76218bb726fb4a888d3",
            "subject": "WIP on main: 934b54645b Merge branch 'agent/deployfix-vercel-ignore-agent-branches-locate-template-2b8589a51fa1'"
          },
          {
            "created_at": 1784695407,
            "ref": "stash@{8}",
            "sha": "f62268028b1848ae429052d6efe8cd4a58b46576",
            "subject": "WIP on main: 0fff15a817 chore: add agent noise files to .gitignore, remove from tracking"
          },
          {
            "created_at": 1784695287,
            "ref": "stash@{9}",
            "sha": "5bfe23de27538a80e00cba3320219ccac08820c6",
            "subject": "WIP on main: 0fff15a817 chore: add agent noise files to .gitignore, remove from tracking"
          },
          {
            "created_at": 1784566224,
            "ref": "stash@{10}",
            "sha": "b82280c0343f4869175541258cddd62174173821",
            "subject": "WIP on main: 5ad886253 merge: fix/ci-baseline into main (resolved conflicts, accepted theirs)"
          },
          {
            "created_at": 1784346942,
            "ref": "stash@{11}",
            "sha": "8e37bdd812a1b44682594e50fba5471a74cb7a57",
            "subject": "WIP on main: 4b853bf4f agent: cade-tribunal-counterparty-inspect-existing-work-and-failure"
          },
          {
            "created_at": 1784183820,
            "ref": "stash@{12}",
            "sha": "f377d8a6501738b70ed7946d66179687407c9683",
            "subject": "WIP on agent/cross-vertical-offset-discovery: 2acb00efb feat(lending): add cross-vertical offset discovery module"
          },
          {
            "created_at": 1784180860,
            "ref": "stash@{13}",
            "sha": "29042af5df843160b32de57366b6a60c0ed3c8a3",
            "subject": "WIP on agent/rework-legal-rework-secret-qafix-tomorrow-07062319-b136250-f9c7e69: 91502905d fix: use npx for vitest to ensure command resolution"
          },
          {
            "created_at": 1784178921,
            "ref": "stash@{14}",
            "sha": "8afae9ad3b1c0bbb3b01581a58b9c19ccd43902a",
            "subject": "WIP on main: 80d18c6a3 feat: add ECP Prisma models, migration, and DB-primary persistence with KV fallback"
          },
          {
            "created_at": 1784170651,
            "ref": "stash@{15}",
            "sha": "4700a51087cdf5e5e6b8e7198527dc854261a3f1",
            "subject": "WIP on warranty-settlement-implement-comprehensive-unit-tests: 3b45f023e fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1784170227,
            "ref": "stash@{16}",
            "sha": "4ae9b1e8eea25b8f1e9b52d980197471915a588a",
            "subject": "WIP on sw-number-lineage-short-kebab-title: 246be2cdb Add authenticated VIGIL receiver"
          },
          {
            "created_at": 1784170098,
            "ref": "stash@{17}",
            "sha": "cf46cd76a5da48faa4f8714ddba15ae3153e199a",
            "subject": "WIP on oracle-indices-as-underlyings: 5d158ac30 feat: rateIndexUnderlying \u2014 rate-index-settled bilateral ECP swaps with drift gate + proof-carrying settlement"
          },
          {
            "created_at": 1784150139,
            "ref": "stash@{18}",
            "sha": "3c04af9f2fad0039864b3e5ced4e1f5d1f70e6cb",
            "subject": "WIP on session/perp-wired-1784149001: 123cc16d3 fix(ecp-coordination-hygiene): correct ecpCredentialing test score expectation"
          },
          {
            "created_at": 1784137671,
            "ref": "stash@{19}",
            "sha": "ff4397a35a6dc930ba9354bb0016c44ba0d64249",
            "subject": "WIP on main: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1784047807,
            "ref": "stash@{20}",
            "sha": "cd8c23bfef82a0ad2a2cfa44da7690bdc420063b",
            "subject": "WIP on main: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1784040589,
            "ref": "stash@{21}",
            "sha": "fc41bca9d2f58777b2cb6446a4745556750372cd",
            "subject": "WIP on agent/capital-relief-filing-exhibit: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1784035868,
            "ref": "stash@{22}",
            "sha": "7ce3eb39fde9bcc82d39ecd953d75b09f3d3c5cf",
            "subject": "WIP on agent/determinations-engine-spec: 8036ad9a fix(build): lower build Node heap 7168->6144 to avoid Vercel builder OOM"
          },
          {
            "created_at": 1784032377,
            "ref": "stash@{23}",
            "sha": "26f707699a2ed5e73c86c55cde19b28c80b5ac35",
            "subject": "WIP on agent/command-bar-ui: 5cf0c10b feat: seed corpus_source_state with historical sources"
          },
          {
            "created_at": 1784003314,
            "ref": "stash@{24}",
            "sha": "190bbf76d34dd7f0e2bdc402d03e9f805413b233",
            "subject": "WIP on agent/ecp-lock-branch: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1783999510,
            "ref": "stash@{25}",
            "sha": "222aeb082ec87fd6bb261a5873eff757d0917ea3",
            "subject": "WIP on agent/oracle-ingest-pareto-indices: 3b45f023 fix: whitelist better-sqlite3 (+prisma/esbuild) build scripts for pnpm v10 \u2014 native bindings now compile on Vercel"
          },
          {
            "created_at": 1783987382,
            "ref": "stash@{26}",
            "sha": "136f81dc8c0df6e0f60b7916937379f48d1bd28d",
            "subject": "WIP on agent/rework-legal-rework-secret-qafix-tomorrow-07062319-b136250-f9c7e69: 482c3041 fix: use npx for vitest to ensure command resolution"
          },
          {
            "created_at": 1783979733,
            "ref": "stash@{27}",
            "sha": "d7703eb99ccb02fcb2ae74668c5a97f8b00b1013",
            "subject": "WIP on agent/bx1-batch: bf8f1287 feat: implement trust-ratchet learning-mode system"
          },
          {
            "created_at": 1783977069,
            "ref": "stash@{28}",
            "sha": "4cfd2c17dd6f8638813f318edd73819364d94c98",
            "subject": "WIP on agent/bx1-batch: be5548d5 agent/bx1: tomorrow-shared-curation-extract, tomorrow-curation-warroom-bridge, tomorrow-warroom-remediation-playbook"
          },
          {
            "created_at": 1783955829,
            "ref": "stash@{29}",
            "sha": "2595f8ad450c1a19e39a78afcb87baa2aabe710e",
            "subject": "WIP on agent/bx3-tomorrow-tasks: b9009174 agent/bx3: sw-contracts sw-netting-utility-api sw-systemic-riskmap sw-stability-simulator sw-demand-foresight-feed"
          }
        ],
        "items_total": 40,
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      },
      {
        "branches": [
          {
            "committed_at": 1784857649,
            "ref": "codex/release-dashboard-auth-20260723",
            "sha": "5c5b3c7a1eb0aba06e759899ecfa1cb79892a4d2",
            "subject": "fix(compliance): unblock access acknowledgment"
          }
        ],
        "count": 1,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      }
    ]
