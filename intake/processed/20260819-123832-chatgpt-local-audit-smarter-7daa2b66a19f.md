PROJECT: smarter

- id: chatgpt-local-reconcile-smarter-7daa2b66a19f
  title: Reconcile local ChatGPT/Codex build evidence for smarter
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
    `7daa2b66a19fb1f32e9e9acc2748b2c503ae094233bd8505439491b3b9b415af`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
        "head": "ba214e3cc4dc0bfec2ed1deead9f7a3658449227",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099241,
        "path": "/Users/kpasch/Documents/smarter-wt/cade-mirror-negotiation"
      },
      {
        "branch": "agent/canary-deepseek-1",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ee424fcfd0fee046ccdebec810b7128beaf37eff",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099294,
        "path": "/Users/kpasch/Documents/smarter-wt/canary-deepseek-1"
      },
      {
        "branch": "agent/cont-5f9e0e",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ee424fcfd0fee046ccdebec810b7128beaf37eff",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099281,
        "path": "/Users/kpasch/Documents/smarter-wt/cont-5f9e0e"
      },
      {
        "branch": "agent/contracts-smarter",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ba214e3cc4dc0bfec2ed1deead9f7a3658449227",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099215,
        "path": "/Users/kpasch/Documents/smarter-wt/contracts-smarter"
      },
      {
        "branch": "agent/counterfactual-replay",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ee424fcfd0fee046ccdebec810b7128beaf37eff",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099254,
        "path": "/Users/kpasch/Documents/smarter-wt/counterfactual-replay"
      },
      {
        "branch": "agent/qafix-pareto-2080-07062319-slice-2-slice-4",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ee424fcfd0fee046ccdebec810b7128beaf37eff",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099306,
        "path": "/Users/kpasch/Documents/smarter-wt/qafix-pareto-2080-07062319-slice-2-slice-4"
      },
      {
        "branch": "agent/rework-secret-a2a-endpoint-0743615",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ee424fcfd0fee046ccdebec810b7128beaf37eff",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099319,
        "path": "/Users/kpasch/Documents/smarter-wt/rework-secret-a2a-endpoint-0743615"
      },
      {
        "branch": "agent/rework-secret-attested-outcomes-9563340",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ee424fcfd0fee046ccdebec810b7128beaf37eff",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099334,
        "path": "/Users/kpasch/Documents/smarter-wt/rework-secret-attested-outcomes-9563340"
      },
      {
        "branch": "agent/rework-secret-tax-return-optimization-cc57fda",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ee424fcfd0fee046ccdebec810b7128beaf37eff",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099352,
        "path": "/Users/kpasch/Documents/smarter-wt/rework-secret-tax-return-optimization-cc57fda"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "844cdf39137a20e8a1331df27effc71bbdeba5e4",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099268,
        "path": "/Users/kpasch/Documents/smarter-wt/session-proof-of-work"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 2,
        "changes": [
          "node_modules",
          "package-lock.json"
        ],
        "changes_digest": "f5098ef7038532f90ff5e1e9be9aacf782532b0061c0f41248f438b7a91d3d9b",
        "head": "89f761708563852afb42f9da9f817a99542a0d50",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787099228,
        "path": "/Users/kpasch/Documents/smarter-wt/smarter-5-95"
      }
    ]
