PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-c29f31f6db0a
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
    `c29f31f6db0a6ecfb168b04c3b2b89e400957855477cc0c8fa7bc57db536df9e`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/contracts-smarter",
        "change_count": 1014,
        "changes_digest": "6b441a3d7de6d774cc2c2e8645e9b48d6b8fcc94e39217bdbf35b23c9d93a76b",
        "changes_sample": [
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-diagnose.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-exec.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-probe-current.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-probe-ecstatic.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-probe-sjd.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-probe.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25T22-57Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25T23-13Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25T23-39Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-25T23-55Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-26T00-09Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-26T19-38Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-26T19-39Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-report-2026-04-26T19-40Z.md",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-24-heisenberg.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-24.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-amazing-nifty-clarke.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-brave-inspiring-mccarthy.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-dazzling-busy-sagan.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-exciting-loving-cerf.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-funny-relaxed-noether.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-gallant-upbeat-hawking.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-gracious-adoring-ride.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-great-upbeat-darwin.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-happy-dreamy.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-intelligent-epic-hawking.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-intelligent-wizardly-gates.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-magical-pasteur.mjs",
          ".archive/opinion-webhook-retry-2026-04-26/opinion-webhook-retry-run-2026-04-25-modest-sharp-allen.mjs"
        ],
        "changes_total": 100,
        "head": "2fb5c64af5682ec5876022e624edf275a21cd57b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/apparently-wt/contracts-smarter"
      }
    ]
