PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-9d7249c816b6
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
    `9d7249c816b6b3b0aef0036b29999a1f6d766b959dec5566f225d9e3c89c3e2d`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/orch-config-consumption",
        "change_count": 58,
        "changes_digest": "7e3a91025a11df3ffc8668b5cbbcaa07b2f57faf964443a8751f5ac9680b0a04",
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
          ".recovery-intent-relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-ident.txt",
          ".recovery-intent-rework-security-relfix-racefeed-07060650-fix-typescript-and-build-slice-4b2a21f-.txt",
          "03_top_opportunities.json",
          "AGENT_COORDINATION.md",
          "BACKLOG-BATCH-7CE8BFB.md",
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
          "app/+html.tsx"
        ],
        "changes_total": 58,
        "head": "3afd588e427f35f1fc721e72e77c015dc44e7fee",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787102482,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/orch-config-consumption"
      },
      {
        "branch": "agent/rework-secret-risk-pool-d48fa2d",
        "change_count": 58,
        "changes_digest": "7e3a91025a11df3ffc8668b5cbbcaa07b2f57faf964443a8751f5ac9680b0a04",
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
          ".recovery-intent-relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-ident.txt",
          ".recovery-intent-rework-security-relfix-racefeed-07060650-fix-typescript-and-build-slice-4b2a21f-.txt",
          "03_top_opportunities.json",
          "AGENT_COORDINATION.md",
          "BACKLOG-BATCH-7CE8BFB.md",
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
          "app/+html.tsx"
        ],
        "changes_total": 58,
        "head": "3afd588e427f35f1fc721e72e77c015dc44e7fee",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787104040,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/rework-secret-risk-pool-d48fa2d"
      },
      {
        "branch": "agent/rework-secret-tax-return-optimization-cc57fda",
        "change_count": 58,
        "changes_digest": "7e3a91025a11df3ffc8668b5cbbcaa07b2f57faf964443a8751f5ac9680b0a04",
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
          ".recovery-intent-relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-ident.txt",
          ".recovery-intent-rework-security-relfix-racefeed-07060650-fix-typescript-and-build-slice-4b2a21f-.txt",
          "03_top_opportunities.json",
          "AGENT_COORDINATION.md",
          "BACKLOG-BATCH-7CE8BFB.md",
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
          "app/+html.tsx"
        ],
        "changes_total": 58,
        "head": "3afd588e427f35f1fc721e72e77c015dc44e7fee",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787104022,
        "path": "/Users/kpasch/Documents/galop/racefeed-wt/rework-secret-tax-return-optimization-cc57fda"
      }
    ]
