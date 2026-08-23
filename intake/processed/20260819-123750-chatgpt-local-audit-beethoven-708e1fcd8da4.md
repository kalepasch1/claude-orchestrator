PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-708e1fcd8da4
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
    `708e1fcd8da4a892d6bf9523e5f092fed9bdaddf4fcf3303f93ce1fcf9a73dff`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 597,
        "items_digest": "696c735a57eaa31276666f433f52aca627f2518f60625d6f1b3c7388763ff05d",
        "items_sample": [
          {
            "created_at": 1785715636,
            "ref": "refs/orch-rescue/20260803T000716-claude-orchestrator",
            "sha": "685bec47743acd2a3a650e4c7f9292b8da075ef6",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715638,
            "ref": "refs/orch-rescue/20260803T000718-breach-remediation",
            "sha": "72bc7ddf1f86a063743b4580974bad1edd05773e",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715639,
            "ref": "refs/orch-rescue/20260803T000719-cade-mirror-negotiation",
            "sha": "696872815d7128b21fb39251cb0dcdf24f766b14",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715640,
            "ref": "refs/orch-rescue/20260803T000720-cc-legacy-margin-removal",
            "sha": "c3d1aa9ea875f4dce9cda820a56c07e55df4aaf4",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715641,
            "ref": "refs/orch-rescue/20260803T000721-cc-mutual-default-fund",
            "sha": "54cb2405c801e47bbd126a557b3493a7463f20ce",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715641,
            "ref": "refs/orch-rescue/20260803T000721-cc-solvency-passport",
            "sha": "cb458638f92ba1b17d86374a7a5961218fa7c224",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715642,
            "ref": "refs/orch-rescue/20260803T000722-convention-conformance-lints",
            "sha": "7530399a51075888d1cbc54c2e5ff897861339e6",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715643,
            "ref": "refs/orch-rescue/20260803T000723-economic-scheduler-revenue",
            "sha": "c23fdeee475de01cec3dd8ec5a4e5e4707ddbfd1",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715644,
            "ref": "refs/orch-rescue/20260803T000724-ext-streaming-terms",
            "sha": "93d532b1c586551809cbba6fe4f035a30ae358bb",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715644,
            "ref": "refs/orch-rescue/20260803T000724-hive-enforcement-velocity-index",
            "sha": "62602aee6fc65c27dc908f8cb07f456ba986f4c9",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715644,
            "ref": "refs/orch-rescue/20260803T000724-merged-diff-memory",
            "sha": "791ce633eed2c06eb9ad96761c0d011e12e5ad4a",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-oc-autoclear-policy",
            "sha": "4202f5b49f2d8b000f169405afd22f90aef70fee",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-orch-config-consumption",
            "sha": "0bee7ff2f1f351dfbe792245978ccd61a70ce238",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-pinned-express-lane",
            "sha": "5f3ed25ef56f6cf9eed2cff816e69bf310dd1d62",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-ploeh-s2s-bridge-tomorrow",
            "sha": "17646f8e58bcc9b86e77bfd282d0bf6dd0fe9efe",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715646,
            "ref": "refs/orch-rescue/20260803T000726-prompt-evolution-bandit",
            "sha": "c724ed32431eeaac9d26c743e5ba0f4892347e7c",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715646,
            "ref": "refs/orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4",
            "sha": "9c023d06b7446d5d97e539979a17e47af66415cb",
            "subject": "On fix-branch: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-breach-remediation",
            "sha": "1ae53af0304da13115a858c5607694cfb32766c8",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cade-mirror-negotiation",
            "sha": "730ac4d5e6b5e53339572abd4b91077d577e197b",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cc-legacy-margin-removal",
            "sha": "eb0f0cb53cb34c4fef57810a6008feeaf9b85b29",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cc-mutual-default-fund",
            "sha": "ef9819ce0821ec013c54c9f1cfcab52fe775aa8e",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cc-solvency-passport",
            "sha": "f87dd5880750cec7466c87ac4e3d359333218d5e",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-claude-orchestrator",
            "sha": "297045a4747551df5dc2c6b7a808782ec162b940",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-convention-conformance-lints",
            "sha": "e4939832797b20ae7a32ea5286eca04cfc717c35",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-economic-scheduler-revenue",
            "sha": "4b70e54e5e84d811e0ea757cc30145b55fa8c90d",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-ext-streaming-terms",
            "sha": "1a057825f68bdbee67f2d25267c09be86fbf6374",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-hive-enforcement-velocity-index",
            "sha": "c9f3f13cb65d42652b97e9acf8fc14fc49722866",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-merged-diff-memory",
            "sha": "6224b1d8130f62992bc7cd2f721d7ef57f843b9c",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-oc-autoclear-policy",
            "sha": "925cb1cb72c51d8a8f873f18594ffcb9a448adda",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-orch-config-consumption",
            "sha": "8e413e3adb3c0a79d7bf19953aac661c094e2f46",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 597,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      },
      {
        "kind": "codex_output_artifact",
        "mtime": 1786496206,
        "path": "/Users/kpasch/Documents/Codex/2026-08-07/cons/outputs/claude-orchestrator--operator-output-truth-session-fabric-20260812.patch",
        "sha256": "889cdfd161402ac769905942e204a740fb3eccd7cad6ea48b96ec8ffe1cbb604",
        "size": 46377
      },
      {
        "branch": "codex/operator-visibility-remediation",
        "change_count": 17,
        "changes": [
          "runner/release_train.py",
          "runner/tests/test_merge_truth.py",
          "runner/tests/test_paused_host_scope.py",
          "supabase/migrations/20260807130000_paused_host_release_guard_v2.sql",
          "web/components/DevelopmentTerminal.vue",
          "web/components/FleetHealthBadge.vue",
          "web/composables/useFleetHealth.ts",
          "web/composables/useOrchestratorSnapshot.ts",
          "web/pages/index.vue",
          "web/server/api/fleet-health.get.ts",
          "web/server/api/orchestrator/snapshot.get.ts",
          "web/server/api/terminal/execute.post.ts",
          "web/server/utils/fleetHealth.test.ts",
          "web/server/utils/fleetHealth.ts",
          "web/server/utils/releaseSurface.test.ts",
          "web/types/fleet-health.ts",
          "web/vitest.config.ts"
        ],
        "changes_digest": "0d5a096cf0c46d4236fbb9b3020bf34bc2db8b5937984dad0ca4fb6cbec3d0ec",
        "head": "fbb735b3cfe402a2ddd2f0ec4fec46c885e61b1b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786107420,
        "path": "/Users/kpasch/Documents/Codex/2026-08-06/figu/work/orchestrator-visibility-remediation"
      },
      {
        "branch": "codex/orchestrator-session-fabric",
        "change_count": 18,
        "changes": [
          "runner/release_train.py",
          "runner/tests/test_paused_host_scope.py",
          "supabase/migrations/20260811160000_paused_host_release_guard_v2.sql",
          "web/components/DevelopmentTerminal.vue",
          "web/components/FleetHealthBadge.vue",
          "web/components/ProofTimeline.vue",
          "web/composables/useFleetHealth.ts",
          "web/composables/useOrchestratorSnapshot.ts",
          "web/pages/index.vue",
          "web/pages/orchestrators/[slug].vue",
          "web/server/api/fleet-health.get.ts",
          "web/server/api/orchestrator/snapshot.get.ts",
          "web/server/api/terminal/execute.post.ts",
          "web/server/utils/fleetHealth.test.ts",
          "web/server/utils/fleetHealth.ts",
          "web/server/utils/releaseSurface.test.ts",
          "web/types/fleet-health.ts",
          "web/vitest.config.ts"
        ],
        "changes_digest": "1cb6a1ef0c2381cb711089be0e4d5a09f34080257e7c853d79dff34412fc56bb",
        "head": "59de85f238e67d19deff89054ded7795f9b22a4a",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786496067,
        "path": "/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric-current"
      },
      {
        "branch": "master",
        "change_count": 3,
        "changes": [
          "PROMPT-ILLUMINATI-ABSORPTION.md",
          "PROMPT-SMARTER-CAPABILITY-BRIDGE.md",
          "cowork-backlog/backlog.json"
        ],
        "changes_digest": "b76768751980bffeb5c76d778b69efda490c6481857c809a0364a3522a0bceb4",
        "head": "8f0a56079815b8d47b87e92180da89fe0dce403b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786417887,
        "path": "/Users/kpasch/Documents/Trojun-orchestrator-misclone-20260812"
      },
      {
        "branch": "DETACHED",
        "change_count": 2,
        "changes": [
          "runner/economic_scheduler.py",
          "runner/tests/test_economic_scheduler_failsoft_repro.py"
        ],
        "changes_digest": "95f8445bc437d639c0c30cbb8e1423283911f44a905fc5fdac7cfd7c2bf8a3c4",
        "head": "1eda33098a1e943d495715cb06271e22f9c4e1a4",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786662371,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-convention-conform-slice-2 8309febb"
      },
      {
        "branch": "DETACHED",
        "change_count": 2,
        "changes": [
          "runner/economic_scheduler.py",
          "runner/tests/test_economic_scheduler_failsoft_repro.py"
        ],
        "changes_digest": "95f8445bc437d639c0c30cbb8e1423283911f44a905fc5fdac7cfd7c2bf8a3c4",
        "head": "76d068867dc2073b53280abfff0fd59a90495507",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786662376,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-update-claude-interface 67280171"
      },
      {
        "branch": "DETACHED",
        "change_count": 2,
        "changes": [
          "runner/economic_scheduler.py",
          "runner/tests/test_economic_scheduler_failsoft_repro.py"
        ],
        "changes_digest": "95f8445bc437d639c0c30cbb8e1423283911f44a905fc5fdac7cfd7c2bf8a3c4",
        "head": "ba57d64f0fb4c760851f178ca7265836159a6846",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786662365,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac 15227eb7"
      },
      {
        "branch": "DETACHED",
        "change_count": 1,
        "changes": [
          "packages/spine/package-lock.json"
        ],
        "changes_digest": "46a7918e82268ce256c4b5a81d6fa95fe57b826dc125bb7a3d75caaccd593873",
        "head": "987e5280e7bf2c0f7e0d598c9ddadc40daec714e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786578520,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/spine-types-x2"
      },
      {
        "count": 4,
        "items": [
          {
            "created_at": 1787040393,
            "ref": "stash@{0}",
            "sha": "9837583420a894d85e4c8a7d8bfab49679d4135a",
            "subject": "On agent/orch-cross-project-depends: sentinel-drift-agent/orch-cross-project-depends-1787040335"
          },
          {
            "created_at": 1787039997,
            "ref": "stash@{1}",
            "sha": "80740fe5fd5fa00007f76d9f28fe11e514673a73",
            "subject": "WIP on master: 527f1ef0 Fix: resource_governor \u2014 convert frozen module constants to live env-var reads so fleet_control tuning changes take effect without restart"
          },
          {
            "created_at": 1787026208,
            "ref": "stash@{2}",
            "sha": "a9f38fd798b8ffbffb9725191bfb66c90ac77187",
            "subject": "WIP on master: 2acd4139 Add comprehensive tests for opportunity_scout.py RICE scoring and proposal filing"
          },
          {
            "created_at": 1787011491,
            "ref": "stash@{3}",
            "sha": "6ca51b977b01731c37d8e975f4015ba3aff66a28",
            "subject": "WIP on master: e5c6c5bf docs: top 3 highest-leverage opportunities from runner codebase scan (RICE-scored)"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      },
      {
        "branches": [
          {
            "committed_at": 1786465525,
            "ref": "chatgpt/chatgpt-local-intake-receipt-safety-20260811-08111725",
            "sha": "30f1b581b055fe14160d2398c47717d98eaffcf4",
            "subject": "chore: apply claude-orchestrator--chatgpt-local-intake-receipt-safety-20260811 (via chatgpt-bridge)"
          },
          {
            "committed_at": 1786492386,
            "ref": "chatgpt/chatgpt-local-queue-bridge-20260811-08111602",
            "sha": "cab66e31b3246c483d5ff753dd5f4a21816aadf6",
            "subject": "fix: serialize local audit registry writers"
          },
          {
            "committed_at": 1786496637,
            "ref": "chatgpt/operator-output-truth-session-fabric-20260812-08120203",
            "sha": "8e22697a6ec8b444ff667a501d7a1669658d9126",
            "subject": "fix(orchestrator): expose delivery truth and fence stale runners"
          },
          {
            "committed_at": 1787008555,
            "ref": "chatgpt/promotion-and-funnel-fixes-20260817-08171915",
            "sha": "591164052780473c7f65864ef2ced240f248e9c1",
            "subject": "ci: put the three new guard suites inside the blocking gate"
          },
          {
            "committed_at": 1787009829,
            "ref": "chatgpt/promotion-funnel-and-prod-urls-20260817-08171936",
            "sha": "41f302b7f4cc4a2a9168a0a7d5f6c1de71f3ebfc",
            "subject": "fix(release-health): two prod_urls were Vercel's login page, and the guard could not see it"
          },
          {
            "committed_at": 1787012761,
            "ref": "chatgpt/promotion-funnel-prod-urls-and-review-fixes-2026-08172022",
            "sha": "0293683202a74704c3b00556cd2e9c797faecfaa",
            "subject": "fix: four defects an adversarial review of my own diff found, three reproduced"
          },
          {
            "committed_at": 1786492554,
            "ref": "codex/pinned-claim-escape",
            "sha": "66b09cbc942767c695738de9d306d09b3babd9c1",
            "subject": "Make pinned tasks visible beyond claim scan cap"
          }
        ],
        "count": 7,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
