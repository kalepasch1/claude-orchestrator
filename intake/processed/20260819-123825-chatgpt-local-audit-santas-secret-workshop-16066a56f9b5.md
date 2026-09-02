PROJECT: santas-secret-workshop

- id: chatgpt-local-reconcile-santas-secret-workshop-16066a56f9b5
  title: Reconcile local ChatGPT/Codex build evidence for santas-secret-workshop
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
    `16066a56f9b5587b5336609eb80f9ecfffcfe87949f76b9821029a6adf73b68e`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "master",
        "change_count": 1,
        "changes": [
          ".convention-rules.json"
        ],
        "changes_digest": "52b17955319c454214d9c65fe286f7f8abc398c6d3cdba375264c0f60a3f5e8e",
        "head": "4f4affe81dfa12294cfa018fe4f7a6a4d59d5428",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786955443,
        "path": "/Users/kpasch/Documents/hisanta"
      },
      {
        "count": 3,
        "items": [
          {
            "created_at": 1784426968,
            "ref": "stash@{0}",
            "sha": "c85c1bad879b33fffbf01bfcf12cf17574b5790e",
            "subject": "WIP on recovery/concurrent-primary-20260715-hisanta: debd26c1 fix: preserve dormant module entrypoints"
          },
          {
            "created_at": 1783973320,
            "ref": "stash@{1}",
            "sha": "355a20bd13a021afab9f4158dc496033a2aca5fa",
            "subject": "WIP on master: fe9214a3 agent/bx2: canary-santas-secret-workshop-20260709 heartbeat"
          },
          {
            "created_at": 1783973224,
            "ref": "stash@{2}",
            "sha": "d32638c6e6f284f770b36c3aa501acdd062461b7",
            "subject": "WIP on master: fe9214a3 agent/bx2: canary-santas-secret-workshop-20260709 heartbeat"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/hisanta"
      }
    ]
