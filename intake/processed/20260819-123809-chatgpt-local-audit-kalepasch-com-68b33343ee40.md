PROJECT: kalepasch-com

- id: chatgpt-local-reconcile-kalepasch-com-68b33343ee40
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
    `68b33343ee40b8c335a1ba7bd517413db126c4264a89e172c1521300013a38ad`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "main",
        "change_count": 2,
        "changes": [
          ".convention-rules.json",
          "package-lock.json"
        ],
        "changes_digest": "cb81cfafc14219c8cfa2e91d47cdcbaf5fa5cb97065ca6dfa45c5a52a7fcb3a8",
        "head": "6da205cfb79d26f0577d8af12b0af0ba60fc0bc0",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787105873,
        "path": "/Users/kpasch/Documents/smarter/pasch"
      },
      {
        "branch": "agent/rework-secret-tax-return-optimization-cc57fda",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "07d01d69b2ab4a919f25faf554aace78c93b9497",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787105897,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/rework-secret-tax-return-optimization-cc57fda"
      }
    ]
