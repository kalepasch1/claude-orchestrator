PROJECT: smarter

- id: chatgpt-local-reconcile-smarter-dd926f89525a
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
    `dd926f89525a417782b2109f45c615fe7313644c78ac5682c041f1216c9247fd`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/canary-ollama-2-2-slice-5",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "c677901c3a65a7e4cb24412100bcba0e2972b3f0",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786738254,
        "path": "/Users/kpasch/Documents/smarter-wt/canary-ollama-2-2-slice-5"
      },
      {
        "branch": "agent/orch-cross-project-depends",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "d90da92d08f5485c8246d494a5d49c5e04c1f337",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786738159,
        "path": "/Users/kpasch/Documents/smarter-wt/orch-cross-project-depends"
      },
      {
        "branch": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "c677901c3a65a7e4cb24412100bcba0e2972b3f0",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786738177,
        "path": "/Users/kpasch/Documents/smarter-wt/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544"
      },
      {
        "branch": "agent/smarter-5-95",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "89f761708563852afb42f9da9f817a99542a0d50",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786738135,
        "path": "/Users/kpasch/Documents/smarter-wt/smarter-5-95"
      }
    ]
