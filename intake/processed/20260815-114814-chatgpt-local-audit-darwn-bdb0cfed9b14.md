PROJECT: darwn

- id: chatgpt-local-reconcile-darwn-bdb0cfed9b14
  title: Reconcile local ChatGPT/Codex build evidence for darwn
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
    `bdb0cfed9b1469fc92105139b88bc899d513f1a3a69034effcb31c16246e0b7e`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 8,
        "items": [
          {
            "created_at": 1785439584,
            "ref": "stash@{0}",
            "sha": "964d888c9fb246d38d82ef74c90838450d152a49",
            "subject": "WIP on agent/backlog-batch-darwn-5b34a9d-slice-4: 6d0fc45 fix: resolve tilde alias in vitest configuration"
          },
          {
            "created_at": 1784926316,
            "ref": "stash@{1}",
            "sha": "e8b5bc7c64f66b23098b8e7c2c99e6767fdc1fae",
            "subject": "WIP on main: 6d0fc45 fix: resolve tilde alias in vitest configuration"
          },
          {
            "created_at": 1784757675,
            "ref": "stash@{2}",
            "sha": "149e9b81987ce696dcefddceeade3d0802d60dbf",
            "subject": "autostash"
          },
          {
            "created_at": 1784686648,
            "ref": "stash@{3}",
            "sha": "9a147daa95c6aee5cb75ac607d08de75b085153f",
            "subject": "WIP on agent/cade-roster-seed-fin: 8e551fc agent/bx2: canary-darwn-20260709 heartbeat"
          },
          {
            "created_at": 1784229220,
            "ref": "stash@{4}",
            "sha": "5df14d7917f03dcdc67e45aa5cac36228ec9bd46",
            "subject": "WIP on recovery/concurrent-primary-20260715-darwn: 785682b recovery: preserve late dormant-source transition"
          },
          {
            "created_at": 1783831777,
            "ref": "stash@{5}",
            "sha": "d8c40ccbb593526244f37aeefa9cbb904e66c6d4",
            "subject": "On agent/reroute-model-keys-mock: wip-before-task-branches"
          },
          {
            "created_at": 1783310605,
            "ref": "stash@{6}",
            "sha": "06c9d22287de0b4ef2198a284b9427c16d6c58c2",
            "subject": "On medicalOnly: recover_and_ship: pre-merge dirt 1783310605"
          },
          {
            "created_at": 1774451483,
            "ref": "stash@{7}",
            "sha": "e63e085bdc8677a8705cbbdaa4818a02706e3fd1",
            "subject": "WIP on main: fc2cd9d adding user home page (working)"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/darwinLife",
        "routing": "darwn"
      }
    ]
