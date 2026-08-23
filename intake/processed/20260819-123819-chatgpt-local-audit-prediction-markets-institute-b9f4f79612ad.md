PROJECT: prediction-markets-institute

- id: chatgpt-local-reconcile-prediction-markets-institute-b9f4f79612ad
  title: Reconcile local ChatGPT/Codex build evidence for prediction-markets-institute
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
    `b9f4f79612adbe9195c456a8aa698432837bfb683d44cca95304fec2dc926d12`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/cade-mirror-negotiation",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103005,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/cade-mirror-negotiation"
      },
      {
        "branch": "agent/canary-deepseek-1",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103039,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/canary-deepseek-1"
      },
      {
        "branch": "agent/cont-5f9e0e",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103025,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/cont-5f9e0e"
      },
      {
        "branch": "agent/contracts-smarter",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787102992,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/contracts-smarter"
      },
      {
        "branch": "agent/counterfactual-replay",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103011,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/counterfactual-replay"
      },
      {
        "branch": "agent/deployfix-darwn-vercel-1783343439",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103033,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/deployfix-darwn-vercel-1783343439"
      },
      {
        "branch": "agent/orch-config-consumption",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "6d7f4cf9a09eda37234341e64888b615c57825c9",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787102987,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/orch-config-consumption"
      },
      {
        "branch": "agent/qafix-pareto-2080-07062319-slice-2-slice-4",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103045,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/qafix-pareto-2080-07062319-slice-2-slice-4"
      },
      {
        "branch": "agent/rework-secret-a2a-endpoint-0743615",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103051,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/rework-secret-a2a-endpoint-0743615"
      },
      {
        "branch": "agent/rework-secret-attested-outcomes-9563340",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103056,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/rework-secret-attested-outcomes-9563340"
      },
      {
        "branch": "agent/rework-secret-mutual-credit-33b3a46",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103065,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/rework-secret-mutual-credit-33b3a46"
      },
      {
        "branch": "agent/rework-secret-tax-return-optimization-cc57fda",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103060,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/rework-secret-tax-return-optimization-cc57fda"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103017,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/session-proof-of-work"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "7cada26ed4323d504b9a04566cfcc5c0dd191258",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787102998,
        "path": "/Users/kpasch/Documents/smarter/prediction-markets-institute/pmi-wt/smarter-5-95"
      }
    ]
