PROJECT: vigil

- id: chatgpt-local-reconcile-vigil-26c14a9fadc8
  title: Reconcile local ChatGPT/Codex build evidence for vigil
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
    `26c14a9fadc84e8281578a91071292d05710d0e82c080415b57a3ee980865dd5`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/canary-deepseek-1",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099962,
        "path": "/Users/kpasch/Documents/vigil-wt/canary-deepseek-1"
      },
      {
        "branch": "agent/cont-5f9e0e",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099944,
        "path": "/Users/kpasch/Documents/vigil-wt/cont-5f9e0e"
      },
      {
        "branch": "agent/counterfactual-replay",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099926,
        "path": "/Users/kpasch/Documents/vigil-wt/counterfactual-replay"
      },
      {
        "branch": "agent/deployfix-darwn-vercel-1783343439",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099953,
        "path": "/Users/kpasch/Documents/vigil-wt/deployfix-darwn-vercel-1783343439"
      },
      {
        "branch": "agent/qafix-pareto-2080-07062319-slice-2-slice-4",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099979,
        "path": "/Users/kpasch/Documents/vigil-wt/qafix-pareto-2080-07062319-slice-2-slice-4"
      },
      {
        "branch": "agent/rework-secret-a2a-endpoint-0743615",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099992,
        "path": "/Users/kpasch/Documents/vigil-wt/rework-secret-a2a-endpoint-0743615"
      },
      {
        "branch": "agent/rework-secret-attested-outcomes-9563340",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787100006,
        "path": "/Users/kpasch/Documents/vigil-wt/rework-secret-attested-outcomes-9563340"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099935,
        "path": "/Users/kpasch/Documents/vigil-wt/session-proof-of-work"
      }
    ]
