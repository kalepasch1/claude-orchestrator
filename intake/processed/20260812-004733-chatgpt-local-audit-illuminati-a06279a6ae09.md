PROJECT: illuminati

- id: chatgpt-local-reconcile-illuminati-a06279a6ae09
  title: Reconcile local ChatGPT/Codex build evidence for illuminati
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
    `a06279a6ae092df39cb584ea087c9cfe8b6df6468bf13ad0bcc33d1afb43f180`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1785182261,
            "ref": "chatgpt/post-hardening-selftest-07271457",
            "sha": "13f7b62bb4531015f9641dce1e1eaa856278ffbe",
            "subject": "chore: post-hardening bridge selftest"
          }
        ],
        "count": 1,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/illuminati"
      }
    ]
