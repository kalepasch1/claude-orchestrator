PROJECT: kalepasch-com

- id: chatgpt-local-reconcile-kalepasch-com-8e5e734cd23d
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
    `8e5e734cd23d1a6e9450f23f282aa2467c73bcca1a7aafce709889bbf7a52235`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
        "head": "ec66e137acb5c5f05a308ef836058b09c0f4adac",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099883,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/canary-deepseek-1"
      },
      {
        "branch": "agent/cont-5f9e0e",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ec66e137acb5c5f05a308ef836058b09c0f4adac",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099841,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/cont-5f9e0e"
      },
      {
        "branch": "agent/contracts-smarter",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ec66e137acb5c5f05a308ef836058b09c0f4adac",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099722,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/contracts-smarter"
      },
      {
        "branch": "agent/counterfactual-replay",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ec66e137acb5c5f05a308ef836058b09c0f4adac",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099773,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/counterfactual-replay"
      },
      {
        "branch": "agent/qafix-pareto-2080-07062319-slice-2-slice-4",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ec66e137acb5c5f05a308ef836058b09c0f4adac",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099911,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/qafix-pareto-2080-07062319-slice-2-slice-4"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ec66e137acb5c5f05a308ef836058b09c0f4adac",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099806,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/session-proof-of-work"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ec66e137acb5c5f05a308ef836058b09c0f4adac",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099748,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/smarter-5-95"
      }
    ]
