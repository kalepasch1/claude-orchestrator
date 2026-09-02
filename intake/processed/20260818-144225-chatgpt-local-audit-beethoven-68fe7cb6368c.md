PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-68fe7cb6368c
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
    `68fe7cb6368c89b7375d22dda0d9a12517cccb231a83fafe80a50ab4f09f6285`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 4,
        "items": [
          {
            "created_at": 1787040393,
            "ref": "stash@{0}",
            "sha": "9837583420a894d85e4c8a7d8bfab49679d4135a",
            "subject": "On agent/orch-cross-project-depends: sentinel-drift-agent/orch-cross-project-depends-1787040335"
          },
          {
            "created_at": 1787039997,
            "ref": "stash@{1}",
            "sha": "80740fe5fd5fa00007f76d9f28fe11e514673a73",
            "subject": "WIP on master: 527f1ef0 Fix: resource_governor \u2014 convert frozen module constants to live env-var reads so fleet_control tuning changes take effect without restart"
          },
          {
            "created_at": 1787026208,
            "ref": "stash@{2}",
            "sha": "a9f38fd798b8ffbffb9725191bfb66c90ac77187",
            "subject": "WIP on master: 2acd4139 Add comprehensive tests for opportunity_scout.py RICE scoring and proposal filing"
          },
          {
            "created_at": 1787011491,
            "ref": "stash@{3}",
            "sha": "6ca51b977b01731c37d8e975f4015ba3aff66a28",
            "subject": "WIP on master: e5c6c5bf docs: top 3 highest-leverage opportunities from runner codebase scan (RICE-scored)"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
