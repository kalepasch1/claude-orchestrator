PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-7df99c040014
  title: Reconcile local ChatGPT/Codex build evidence for racefeed
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
    `7df99c040014cf861cc344528581cbd63837da8a429de72ababbdd81491f0b41`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 5,
        "items": [
          {
            "created_at": 1785591491,
            "ref": "stash@{0}",
            "sha": "d88310362b8c4d1c6931032bac265994296efe36",
            "subject": "On (no branch): preserve-racefeed-integration-2026-07-31"
          },
          {
            "created_at": 1784862309,
            "ref": "stash@{1}",
            "sha": "776cddc499dbac3b6fcd7fe1c7d12587609f9c00",
            "subject": "WIP on master: f0ed1ce Merge remote-tracking branch 'origin/agent/relfix-racefeed-07060650-split-build-task-into-smaller-sub-tasks'"
          },
          {
            "created_at": 1784002745,
            "ref": "stash@{2}",
            "sha": "42287b1ed4d0a32948ddec0bf8554cc0c5844f1c",
            "subject": "WIP on agent/toolchain-repair-6096aa2b: 81f5e54 fix: restore missing oddsLabel export and Pick type import in lib/odds.ts"
          },
          {
            "created_at": 1783986567,
            "ref": "stash@{3}",
            "sha": "9add623e61cc2b6db0f5b948c2449fa70a6f1bb8",
            "subject": "On (no branch): manual-restore-1783986567"
          },
          {
            "created_at": 1783985412,
            "ref": "stash@{4}",
            "sha": "b29b2ee872ae31f76b303aedf3963973ad5d9d90",
            "subject": "WIP on ws2-clip-video-margin: 22cd5f7 WIP preserve in-progress work"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      }
    ]
