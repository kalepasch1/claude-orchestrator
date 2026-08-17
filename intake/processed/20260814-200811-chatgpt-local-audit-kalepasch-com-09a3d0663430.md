PROJECT: kalepasch-com

- id: chatgpt-local-reconcile-kalepasch-com-09a3d0663430
  title: Reconcile local ChatGPT/Codex build evidence for kalepasch-com
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
    `09a3d06634301a8e25ae38d2d1d1dd2f92d24c8ab02205b95b9bb26b95d766c6`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/canary-ollama-2-2-slice-5",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694892,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/canary-ollama-2-2-slice-5"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694808,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694829,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694872,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests"
      },
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694853,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter"
      },
      {
        "branch": "agent/orch-cross-project-depends",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694734,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/orch-cross-project-depends"
      },
      {
        "branch": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694789,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch"
      },
      {
        "branch": "agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694770,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db"
      },
      {
        "branch": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694750,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786694695,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/smarter-5-95"
      }
    ]
