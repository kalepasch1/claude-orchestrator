PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-50b14aba0459
  title: Reconcile local ChatGPT/Codex build evidence for racefeed
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
    `50b14aba0459bf343ce923884a879b8f307e2ba30f1f9a3885eb01b1440fafa2`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 1,
        "changes": [
          "OPPORTUNITIES.json"
        ],
        "changes_digest": "cc169be5315c7539d225b64a482d557eea305ba105de74a14ff5e26c02b9fa99",
        "head": "97ebfe4e6f8a3e01aefc5aa7aec6eae14ab8e07e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786059582,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/c129734ad13bbee1e964"
      },
      {
        "branch": "agent/cade-adversary-tournaments",
        "change_count": 56,
        "changes_digest": "9deb6c577774a73ed7ac17d3e585e3e5aee1b1ab5aba4a04b235be88aec0e320",
        "changes_sample": [
          ".deploy-canary",
          ".lintstagedrc.json",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-improve-common-brain-racing-data-intelligence-feed.txt",
          ".recovery-intent-improve-mesh-galop-racing-intelligence-market.txt",
          ".recovery-intent-qafix-racefeed-07180346.txt",
          ".recovery-intent-qafix-racefeed-65f785fa31a3-reproduce-racefeed-race-condition.txt",
          ".recovery-intent-recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2.txt",
          ".recovery-intent-recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-3.txt",
          ".recovery-intent-recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-5.txt",
          ".recovery-intent-relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-docum.txt",
          ".recovery-intent-rework-security-relfix-racefeed-07060650-fix-typescript-and-build-slice-4b2a21f-.txt",
          "03_top_opportunities.json",
          "AGENT_COORDINATION.md",
          "COMMIT_MANIFEST.md",
          "IMPLEMENTATION_SUMMARY.md",
          "LICENSE",
          "app.json",
          "app/(auth)/_layout.tsx",
          "app/(auth)/index.tsx",
          "app/(tabs)/_layout.tsx",
          "app/(tabs)/index.tsx",
          "app/(tabs)/leaderboard.tsx",
          "app/(tabs)/more.tsx",
          "app/(tabs)/profile.tsx",
          "app/(tabs)/tips.tsx",
          "app/(tabs)/today.tsx",
          "app/+html.tsx",
          "app/_layout.tsx",
          "app/card/[track].tsx"
        ],
        "changes_total": 56,
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786227847,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cade-adversary-tournaments"
      },
      {
        "branch": "agent/cade-certificate-proof-constitution",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786234104,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cade-certificate-proof-constitution"
      },
      {
        "branch": "agent/cade-mirror-negotiation",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786228939,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cade-mirror-negotiation"
      },
      {
        "branch": "agent/cade-persona-synthesis-evidence",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786234135,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cade-persona-synthesis-evidence"
      },
      {
        "branch": "agent/cade-portfolio-var",
        "change_count": 56,
        "changes_digest": "9deb6c577774a73ed7ac17d3e585e3e5aee1b1ab5aba4a04b235be88aec0e320",
        "changes_sample": [
          ".deploy-canary",
          ".lintstagedrc.json",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt",
          ".recovery-intent-improve-common-brain-racing-data-intelligence-feed.txt",
          ".recovery-intent-improve-mesh-galop-racing-intelligence-market.txt",
          ".recovery-intent-qafix-racefeed-07180346.txt",
          ".recovery-intent-qafix-racefeed-65f785fa31a3-reproduce-racefeed-race-condition.txt",
          ".recovery-intent-recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2.txt",
          ".recovery-intent-recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-3.txt",
          ".recovery-intent-recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-5.txt",
          ".recovery-intent-relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-docum.txt",
          ".recovery-intent-rework-security-relfix-racefeed-07060650-fix-typescript-and-build-slice-4b2a21f-.txt",
          "03_top_opportunities.json",
          "AGENT_COORDINATION.md",
          "COMMIT_MANIFEST.md",
          "IMPLEMENTATION_SUMMARY.md",
          "LICENSE",
          "app.json",
          "app/(auth)/_layout.tsx",
          "app/(auth)/index.tsx",
          "app/(tabs)/_layout.tsx",
          "app/(tabs)/index.tsx",
          "app/(tabs)/leaderboard.tsx",
          "app/(tabs)/more.tsx",
          "app/(tabs)/profile.tsx",
          "app/(tabs)/tips.tsx",
          "app/(tabs)/today.tsx",
          "app/+html.tsx",
          "app/_layout.tsx",
          "app/card/[track].tsx"
        ],
        "changes_total": 56,
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786227952,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cade-portfolio-var"
      },
      {
        "branch": "agent/cade-reputation-compositions",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786228977,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cade-reputation-compositions"
      },
      {
        "branch": "agent/convention-conformance-lints",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786234013,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/convention-conformance-lints"
      },
      {
        "branch": "agent/cross-app-knowledge-bus",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786228945,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cross-app-knowledge-bus"
      },
      {
        "branch": "agent/dag-aware-intake",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786234046,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/dag-aware-intake"
      },
      {
        "branch": "agent/fix-prompt-delivery-bug",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786228962,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/fix-prompt-delivery-bug"
      },
      {
        "branch": "agent/merge-train-serializer",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786234155,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/merge-train-serializer"
      },
      {
        "branch": "agent/merged-diff-memory",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786233988,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/merged-diff-memory"
      },
      {
        "branch": "agent/orch-config-consumption",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786237994,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/orch-config-consumption"
      },
      {
        "branch": "agent/rls-regression-ci-gate",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786234085,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/rls-regression-ci-gate"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786238076,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/session-proof-of-work"
      },
      {
        "branch": "agent/shared-world-model",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786238021,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/shared-world-model"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786228927,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/smarter-5-95"
      },
      {
        "branches": [
          {
            "committed_at": 1786136527,
            "ref": "agent/qafix-racefeed-07180346-fix-downstream-agentledger-test",
            "sha": "d694b92cb21279d52c511fe0f35487b5fe72aded",
            "subject": "recovery-intent-stub: qafix-racefeed-07180346-fix-downstream-agentledger-test"
          },
          {
            "committed_at": 1786143665,
            "ref": "agent/qafix-racefeed-07180346-verify-full-qa-gate",
            "sha": "b4e677dc2b382234a40daae681dcdbee95e54f20",
            "subject": "recovery-intent-stub: qafix-racefeed-07180346-verify-full-qa-gate"
          },
          {
            "committed_at": 1786122891,
            "ref": "agent/qafix-racefeed-5a072f924ba3",
            "sha": "870c2daf5eb685d9ce7e5ba1c354c50eb5da2d06",
            "subject": "regen-from-cache(template): qafix-racefeed-5a072f924ba3"
          },
          {
            "committed_at": 1786130133,
            "ref": "agent/qafix-racefeed-65f785fa31a3-add-regression-test-and-commit",
            "sha": "273e905f4bbdf47bb44059e55c31429f11353b47",
            "subject": "regen-from-cache(template): qafix-racefeed-65f785fa31a3-add-regression-test-and-commit"
          },
          {
            "committed_at": 1786128347,
            "ref": "agent/qafix-racefeed-65f785fa31a3-reproduce-racefeed-race-condition",
            "sha": "804f2b01480c6d9d9b64de4bf0dea822a8371e43",
            "subject": "regen-from-cache(template): qafix-racefeed-65f785fa31a3-reproduce-racefeed-race-condition"
          },
          {
            "committed_at": 1786119940,
            "ref": "agent/qafix-racefeed-daefef96359a",
            "sha": "40bc9b29dd5c41efaf9e92008354b0976b951931",
            "subject": "regen-from-cache(template): qafix-racefeed-daefef96359a"
          },
          {
            "committed_at": 1786137110,
            "ref": "agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2",
            "sha": "f1ec21396e936e86f835ebd836620682e3d46f58",
            "subject": "recovery-intent-stub: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2"
          },
          {
            "committed_at": 1786135714,
            "ref": "agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-3",
            "sha": "c87aeef8993e2ec4b8846ccf9b9fcbe8da15c351",
            "subject": "recovery-intent-stub: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-3"
          },
          {
            "committed_at": 1786140327,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-ident",
            "sha": "3bfc287a1a67371683959d0058dadbb271e5b013",
            "subject": "recovery-intent-stub: relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-ident"
          },
          {
            "committed_at": 1786140574,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-inves",
            "sha": "648dfe40c87ee6fe5103df077dca32171f3d6341",
            "subject": "recovery-intent-stub: relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-inves"
          },
          {
            "committed_at": 1785861561,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-source-config",
            "sha": "f0a41d3a6dd8bdd73f91456339d136ce14097d63",
            "subject": "agent: relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-source-config \u2014 commonBrain.test runnable under node --test (.ts import, node:test+assert expect shim); fetch-nodeshim -> local stub; npm test 84/84, tsc clean"
          },
          {
            "committed_at": 1786159356,
            "ref": "agent/remediate-noop-relfix-racefeed-07060650-sub-task-3-slice-1",
            "sha": "4d104abfa394dc90ec37c425e4857b78e3256de4",
            "subject": "regen-from-cache(template): remediate-noop-relfix-racefeed-07060650-sub-task-3-slice-1"
          },
          {
            "committed_at": 1786151467,
            "ref": "agent/remediate-relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-fai",
            "sha": "918061a14892f6c7a309374d2d265025b742ab27",
            "subject": "regen-from-cache(merged_diff): remediate-relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-fai"
          },
          {
            "committed_at": 1786140469,
            "ref": "agent/rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c-test-and-ver",
            "sha": "370a4505c6136772aed528d0264dfd8af98a5cae",
            "subject": "recovery-intent-stub: rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c-test-and-ver"
          },
          {
            "committed_at": 1786135055,
            "ref": "agent/rework-noop-relfix-racefeed-07060650-sub-task-3-commit-package-files-if-c9074df-",
            "sha": "6cd446693764dc26808329c7205c919622d16b4f",
            "subject": "regen-from-cache(template): rework-noop-relfix-racefeed-07060650-sub-task-3-commit-package-files-if-c9074df-"
          },
          {
            "committed_at": 1786134923,
            "ref": "agent/toolchain-repair-6096aa2b-fix-node-modules-install-slice-2",
            "sha": "1bff9f559f48a1129617b2bbd815a1c10f9d8310",
            "subject": "recovery-intent-stub: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2"
          },
          {
            "committed_at": 1786135714,
            "ref": "agent/toolchain-repair-6096aa2b-fix-node-modules-install-slice-3",
            "sha": "c87aeef8993e2ec4b8846ccf9b9fcbe8da15c351",
            "subject": "recovery-intent-stub: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-3"
          },
          {
            "committed_at": 1786450235,
            "ref": "master",
            "sha": "2491788585fea614e257352038013624896f2164",
            "subject": "fix: stop tracking regenerated local state"
          },
          {
            "committed_at": 1786119940,
            "ref": "orchestrator/dev",
            "sha": "40bc9b29dd5c41efaf9e92008354b0976b951931",
            "subject": "regen-from-cache(template): qafix-racefeed-daefef96359a"
          }
        ],
        "count": 19,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      },
      {
        "count": 501,
        "items_digest": "157fea4445c816d039790a7b8442e297c0d00a257438d43b6c2f7400fe974217",
        "items_sample": [
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-c129734ad13bbee1e964",
            "sha": "4e7e86ff6f80dad2280413f2d0d5e485aa2ba1d6",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-c129734ad13bbee1e964-run-10003-1785714283532053000",
            "sha": "7cd5e0cf9082a898d053a7a17002763821313edb",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-c129734ad13bbee1e964-run-10250-1785715032492371000",
            "sha": "7cd5e0cf9082a898d053a7a17002763821313edb",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-racefeed",
            "sha": "b4939da0fa03dd1feba5f09c793f26c7b38228c4",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-1062-1785714246095212000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-11612-1785702608206761000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-12006-1785711020144387000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-12388-1785713360538091000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-12448-1785703241539186000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-14209-1785701171387059000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-15949-1785712120354334000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-17048-1785704623361813000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-17705-1785704242223916000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-18152-1785702659363173000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-1841-1785703183797676000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-18884-1785703675300363000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-1904-1785711842749694000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-23271-1785703308068809000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-2419-1785702539401135000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-24375-1785703972292415000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-24921-1785705658250344000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-25413-1785701874685170000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-25451-1785711082523069000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-26090-1785714486918844000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-2779-1785713287902734000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-28279-1785715124821854000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-28297-1785712211071765000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-30547-1785704287844482000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-32777-1785703371604035000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715603,
            "ref": "refs/orch-rescue/20260803T000643-c129734ad13bbee1e964-run-33673-1785710580945483000",
            "sha": "5741033c38e4fdc3690db445ff8c125334343720",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          }
        ],
        "items_total": 501,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      },
      {
        "count": 5,
        "items": [
          {
            "created_at": 1785591491,
            "ref": "stash@{0}",
            "sha": "d88310362b8c4d1c6931032bac265994296efe36",
            "subject": "On (no branch): preserve-racefeed-integration-2026-07-31"
          },
          {
            "created_at": 1784862309,
            "ref": "stash@{1}",
            "sha": "776cddc499dbac3b6fcd7fe1c7d12587609f9c00",
            "subject": "WIP on master: f0ed1ce Merge remote-tracking branch 'origin/agent/relfix-racefeed-07060650-split-build-task-into-smaller-sub-tasks'"
          },
          {
            "created_at": 1784002745,
            "ref": "stash@{2}",
            "sha": "42287b1ed4d0a32948ddec0bf8554cc0c5844f1c",
            "subject": "WIP on agent/toolchain-repair-6096aa2b: 81f5e54 fix: restore missing oddsLabel export and Pick type import in lib/odds.ts"
          },
          {
            "created_at": 1783986567,
            "ref": "stash@{3}",
            "sha": "9add623e61cc2b6db0f5b948c2449fa70a6f1bb8",
            "subject": "On (no branch): manual-restore-1783986567"
          },
          {
            "created_at": 1783985412,
            "ref": "stash@{4}",
            "sha": "b29b2ee872ae31f76b303aedf3963973ad5d9d90",
            "subject": "WIP on ws2-clip-video-margin: 22cd5f7 WIP preserve in-progress work"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      }
    ]
