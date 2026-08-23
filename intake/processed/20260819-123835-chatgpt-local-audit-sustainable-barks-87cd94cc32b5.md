PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-87cd94cc32b5
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
    `87cd94cc32b5d1e6042504b6ac617ad0ff5b9c6f63379b833f86946490c8feef`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/cade-mirror-negotiation",
        "change_count": 2,
        "changes": [
          "node_modules",
          "package-lock.json"
        ],
        "changes_digest": "f5098ef7038532f90ff5e1e9be9aacf782532b0061c0f41248f438b7a91d3d9b",
        "head": "00309c1854d3aaaebf12bd48d3cf779527666e96",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101278,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/cade-mirror-negotiation"
      },
      {
        "branch": "agent/canary-deepseek-1",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "0ab0d5bae5c49989871dab31909866f7f4a7bc25",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101301,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/canary-deepseek-1"
      },
      {
        "branch": "agent/cont-5f9e0e",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "0ab0d5bae5c49989871dab31909866f7f4a7bc25",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101291,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/cont-5f9e0e"
      },
      {
        "branch": "agent/contracts-smarter",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "5a6dc4fdb416071b7edf6ac78134e6d884b880f2",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101267,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/contracts-smarter"
      },
      {
        "branch": "agent/counterfactual-replay",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "31725a9700e3ee6506c71c5359d75c978416486b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101282,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/counterfactual-replay"
      },
      {
        "branch": "agent/deployfix-darwn-vercel-1783343439",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "0ab0d5bae5c49989871dab31909866f7f4a7bc25",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101301,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/deployfix-darwn-vercel-1783343439"
      },
      {
        "branch": "agent/qafix-pareto-2080-07062319-slice-2-slice-4",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "0ab0d5bae5c49989871dab31909866f7f4a7bc25",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101310,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/qafix-pareto-2080-07062319-slice-2-slice-4"
      },
      {
        "branch": "agent/rework-secret-a2a-endpoint-0743615",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "31725a9700e3ee6506c71c5359d75c978416486b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101310,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rework-secret-a2a-endpoint-0743615"
      },
      {
        "branch": "agent/rework-secret-attested-outcomes-9563340",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "31725a9700e3ee6506c71c5359d75c978416486b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101320,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rework-secret-attested-outcomes-9563340"
      },
      {
        "branch": "agent/rework-secret-tax-return-optimization-cc57fda",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "31725a9700e3ee6506c71c5359d75c978416486b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101320,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/rework-secret-tax-return-optimization-cc57fda"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 2,
        "changes": [
          "node_modules",
          "package-lock.json"
        ],
        "changes_digest": "f5098ef7038532f90ff5e1e9be9aacf782532b0061c0f41248f438b7a91d3d9b",
        "head": "e4b08acaba04bf4e2d72dd993eeda497a0499674",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101292,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/session-proof-of-work"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 2,
        "changes": [
          "node_modules",
          "package-lock.json"
        ],
        "changes_digest": "f5098ef7038532f90ff5e1e9be9aacf782532b0061c0f41248f438b7a91d3d9b",
        "head": "00309c1854d3aaaebf12bd48d3cf779527666e96",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787101273,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/smarter-5-95"
      }
    ]
