PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-83a8a5533024
  title: Reconcile local ChatGPT/Codex build evidence for sustainable-barks
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
    `83a8a5533024428f58e20fa75fad9bcc74b6789adf80cdd9fa2ff3438be7d355`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
        "head": "00309c1854d3aaaebf12bd48d3cf779527666e96",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786496070,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/cade-mirror-negotiation"
      },
      {
        "branch": "agent/cross-app-knowledge-bus",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "e4b08acaba04bf4e2d72dd993eeda497a0499674",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786496310,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/cross-app-knowledge-bus"
      },
      {
        "branch": "agent/cx-determination-slo",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "e4b08acaba04bf4e2d72dd993eeda497a0499674",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786493412,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/cx-determination-slo"
      },
      {
        "branch": "agent/cx-shadow-cade",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "e4b08acaba04bf4e2d72dd993eeda497a0499674",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786493396,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/cx-shadow-cade"
      },
      {
        "branch": "agent/deploy-journey-verification",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "e4b08acaba04bf4e2d72dd993eeda497a0499674",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786493379,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/deploy-journey-verification"
      },
      {
        "branch": "agent/merged-diff-memory",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "00309c1854d3aaaebf12bd48d3cf779527666e96",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786495468,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/merged-diff-memory"
      },
      {
        "branch": "agent/orch-config-consumption",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "e4b08acaba04bf4e2d72dd993eeda497a0499674",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786494939,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/orch-config-consumption"
      },
      {
        "branch": "agent/orch-cross-project-depends",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "fa12fac29f2df4aca4126817b167d91e2da4de6a",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786493439,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/orch-cross-project-depends"
      },
      {
        "branch": "agent/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "dda9154db227b4766b04668a74535f57c6fd2275",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786493469,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f"
      },
      {
        "branch": "agent/rls-regression-ci-gate",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "e4b08acaba04bf4e2d72dd993eeda497a0499674",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786496463,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rls-regression-ci-gate"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "e4b08acaba04bf4e2d72dd993eeda497a0499674",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786496515,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/session-proof-of-work"
      },
      {
        "branch": "agent/shared-world-model",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "e4b08acaba04bf4e2d72dd993eeda497a0499674",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786496403,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/shared-world-model"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "00309c1854d3aaaebf12bd48d3cf779527666e96",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786495679,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/smarter-5-95"
      }
    ]
