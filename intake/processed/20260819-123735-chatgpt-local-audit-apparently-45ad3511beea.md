PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-45ad3511beea
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
    `45ad3511beea21846a340b4da95b7300c3ed522cbe4642912c31f86695278ff7`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "consolidation/verified-merges-20260817",
        "change_count": 11,
        "changes": [
          ".claude/settings.json",
          ".convention-rules.json",
          ".landing-verify.sh",
          ".probe2.mjs",
          ".supabase-applied.json",
          "scripts/.tmp-dryrun-525.mjs",
          "server/__tests__/api-exchange.test.ts",
          "server/utils/governance.ts",
          "triage-run-2026-08-11-HALTED.md",
          "triage-run-2026-08-11.md",
          "triage-run-2026-08-12.md"
        ],
        "changes_digest": "9a3f6d0ba62d43477a8079be7eac51f51802eddf0e47619c302bce369b9140a0",
        "head": "d5328ec32a8f3c1d672e7c0cb7b3563845b8645f",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787083380,
        "path": "/Users/kpasch/Documents/apparently"
      }
    ]
