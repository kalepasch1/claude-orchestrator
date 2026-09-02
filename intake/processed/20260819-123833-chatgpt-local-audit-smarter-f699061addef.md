PROJECT: smarter

- id: chatgpt-local-reconcile-smarter-f699061addef
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
    `f699061addefa4886ae2c62283dad80dfc30b1d4aa0ca8ca177a205d8b8fd7e4`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "orchestrator/dev",
        "change_count": 3,
        "changes": [
          ".convention-rules.json",
          "pasch",
          "prediction-markets-institute/pmi"
        ],
        "changes_digest": "be95566e34d60013d3e392c44e80ceebb25fe2604ac3c4f4645af989618c9dc1",
        "head": "4a82f24ff234508290c2faecb98a9a2d08b0d785",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787106423,
        "path": "/Users/kpasch/Documents/smarter"
      },
      {
        "branch": "agent/rework-secret-risk-pool-d48fa2d",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "ee424fcfd0fee046ccdebec810b7128beaf37eff",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787105395,
        "path": "/Users/kpasch/Documents/smarter-wt/rework-secret-risk-pool-d48fa2d"
      }
    ]
