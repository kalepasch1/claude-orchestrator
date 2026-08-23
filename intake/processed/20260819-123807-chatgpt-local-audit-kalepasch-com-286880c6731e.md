PROJECT: kalepasch-com

- id: chatgpt-local-reconcile-kalepasch-com-286880c6731e
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
    `286880c6731e933d66a9b8832e1ca9861d0e782b0ebb4de943cce44f4aa9497e`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 1,
        "items": [
          {
            "created_at": 1784696963,
            "ref": "stash@{0}",
            "sha": "628a45ec5449647390b11ad2b3d46f7945e4e72c",
            "subject": "WIP on main: dd4f870 fix: use current Vigil and Triage marks"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/pasch"
      },
      {
        "count": 1,
        "items": [
          {
            "created_at": 1784686645,
            "ref": "stash@{0}",
            "sha": "af26c6e3a978bba35180ee5d706f548bceb4dc8f",
            "subject": "WIP on main: 796ae37 Add public authority and briefing surfaces"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/smarter/pasch"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/pasch",
        "routing": "kalepasch-com"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/vinci",
        "routing": "kalepasch-com"
      }
    ]
