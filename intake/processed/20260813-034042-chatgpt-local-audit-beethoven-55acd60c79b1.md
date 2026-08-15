PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-55acd60c79b1
  title: Reconcile local ChatGPT/Codex build evidence for beethoven
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
    `55acd60c79b1454f3b5bb602262484397479b5e6283c3dd57438909e1a6c8c27`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/improve-compliance-durable-event-router",
        "change_count": 4,
        "changes": [
          "runner/compliance_event_router.py",
          "runner/compliance_event_stream.py",
          "runner/tests/conftest.py",
          "runner/tests/test_compliance_event_router.py"
        ],
        "changes_digest": "000d6f0f5698e4d58961c1675042567d3562d5fcd257f0874f8454a9778842f8",
        "head": "c635b983bda927610bd321f96c9421715f6214f5",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786531005,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/evrouter"
      }
    ]
