PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-c1e713251eec
  title: Reconcile local ChatGPT/Codex build evidence for sustainable-barks
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
    `c1e713251eecb29b7aaf58c7df06ee4930213c7ec87764d0e3fc4a4e586402fd`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 5,
        "items": [
          {
            "created_at": 1785429738,
            "ref": "stash@{0}",
            "sha": "8a9cd1c2bc65428f6a800326c4072f5f1b126265",
            "subject": "WIP on orchestrator/dev: a82b6ff Merge agent/funding-equilibrium: cleanup obsolete composables, middleware, config artifacts"
          },
          {
            "created_at": 1784986273,
            "ref": "stash@{1}",
            "sha": "a8f8ba184283aa9ef89485646c2952ba452f365c",
            "subject": "WIP on main: 45810f5 fix: regenerate package-lock.json in sync with package.json"
          },
          {
            "created_at": 1784427673,
            "ref": "stash@{2}",
            "sha": "31b76a46c89a5f182a496515fd504ff7260de175",
            "subject": "WIP on agent/recover-missing-branch-canary-sustainable-barks-20260708-slice-1: 6285c9a agent: recover-missing-branch-canary-sustainable-barks-20260708-slice-1 \u2014 add rate-limit memory guard and test helper"
          },
          {
            "created_at": 1784427537,
            "ref": "stash@{3}",
            "sha": "d87a1cb4de8aef4da609df839d33644aeaafc6ba",
            "subject": "WIP on agent/recover-missing-branch-canary-sustainable-barks-20260708-slice-1: 6285c9a agent: recover-missing-branch-canary-sustainable-barks-20260708-slice-1 \u2014 add rate-limit memory guard and test helper"
          },
          {
            "created_at": 1783973183,
            "ref": "stash@{4}",
            "sha": "43bc336bf6008b94ae5add891018543cf8b02045",
            "subject": "WIP on main: f71e3db agent/bx2: canary-sustainable-barks-20260709 heartbeat"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/Sustainable_Barks"
      }
    ]
