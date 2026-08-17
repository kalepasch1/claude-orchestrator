PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-5e8f7ec6f6d7
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
    `5e8f7ec6f6d7f2524cda4a1582ca83157281d1fdd85c37528f79c541b38b36ae`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/cade-mirror-negotiation",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "24bd6ea3d402b0f61e18f3dd8835b0f52bfea8f8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786493144,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cade-mirror-negotiation"
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
        "newest_change_mtime": 1786493093,
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
        "newest_change_mtime": 1786493673,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cross-app-knowledge-bus"
      },
      {
        "branch": "agent/cx-determination-slo",
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
        "newest_change_mtime": 1786496132,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cx-determination-slo"
      },
      {
        "branch": "agent/cx-shadow-cade",
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
        "newest_change_mtime": 1786496233,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/cx-shadow-cade"
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
        "newest_change_mtime": 1786493071,
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
        "newest_change_mtime": 1786493045,
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
        "newest_change_mtime": 1786493160,
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
        "newest_change_mtime": 1786493695,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/session-proof-of-work"
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
        "newest_change_mtime": 1786493124,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/smarter-5-95"
      }
    ]
