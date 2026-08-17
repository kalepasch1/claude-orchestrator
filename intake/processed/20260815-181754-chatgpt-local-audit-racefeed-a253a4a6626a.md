PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-a253a4a6626a
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
    `a253a4a6626a1017d2db061f0d10aff6fb82789bae5d2acadc3b7f736c729fac`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786794221,
            "ref": "agent/chatgpt-local-reconcile-racefeed-54a71fe5564f",
            "sha": "2e47b7843182a3bb3fa0c040f34d1bd6fd747206",
            "subject": "agent: chatgpt-local-reconcile-racefeed-54a71fe5564f"
          },
          {
            "committed_at": 1786794271,
            "ref": "agent/chatgpt-local-reconcile-racefeed-6746994b1052",
            "sha": "c23fb98f8377b30b321cc4f85cf543bf73f07368",
            "subject": "agent: chatgpt-local-reconcile-racefeed-6746994b1052"
          },
          {
            "committed_at": 1785861561,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-source-config",
            "sha": "f0a41d3a6dd8bdd73f91456339d136ce14097d63",
            "subject": "agent: relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-source-config \u2014 commonBrain.test runnable under node --test (.ts import, node:test+assert expect shim); fetch-nodeshim -> local stub; npm test 84/84, tsc clean"
          }
        ],
        "count": 3,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      }
    ]
