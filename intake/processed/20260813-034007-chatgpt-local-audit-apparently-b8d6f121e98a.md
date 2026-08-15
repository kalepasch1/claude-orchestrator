PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-b8d6f121e98a
  title: Reconcile local ChatGPT/Codex build evidence for apparently
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
    `b8d6f121e98a591e90b471202c097e4c30db87a7b86745a0d1a996f201918b96`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/triage-orch-rescue-refs-backlog",
        "change_count": 2,
        "changes": [
          "scripts/triage-orch-rescue-refs.mjs",
          "tests/triage-orch-rescue-refs.test.ts"
        ],
        "changes_digest": "fc866edb54221d23cbf28588a2628c6ec5f6d8b794a5dc2e35b721ca6a853db2",
        "head": "4e4e7f8b10cb328ba13c40d7ee25c1aeaec1a9a8",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786530935,
        "path": "/Users/kpasch/Documents/apparently-wt/triage-orch-rescue-refs-backlog"
      }
    ]
