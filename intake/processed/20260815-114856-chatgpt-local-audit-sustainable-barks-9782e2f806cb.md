PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-9782e2f806cb
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
    `9782e2f806cbeb67f22249d76a89265c5c78c817b951d13147440787a13bab1e`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
        "newest_change_mtime": 1786739642,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/cade-mirror-negotiation"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "dda9154db227b4766b04668a74535f57c6fd2275",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739710,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "dda9154db227b4766b04668a74535f57c6fd2275",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739716,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "dda9154db227b4766b04668a74535f57c6fd2275",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739736,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "dda9154db227b4766b04668a74535f57c6fd2275",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739728,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter"
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
        "newest_change_mtime": 1786739658,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/orch-cross-project-depends"
      },
      {
        "branch": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "dda9154db227b4766b04668a74535f57c6fd2275",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739703,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch"
      },
      {
        "branch": "agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "dda9154db227b4766b04668a74535f57c6fd2275",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739698,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db"
      },
      {
        "branch": "agent/rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "dda9154db227b4766b04668a74535f57c6fd2275",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739677,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c"
      },
      {
        "branch": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "dda9154db227b4766b04668a74535f57c6fd2275",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786739685,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544"
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
        "newest_change_mtime": 1786739668,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f"
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
        "newest_change_mtime": 1786739649,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/session-proof-of-work"
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
        "newest_change_mtime": 1786739633,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/smarter-5-95"
      }
    ]
