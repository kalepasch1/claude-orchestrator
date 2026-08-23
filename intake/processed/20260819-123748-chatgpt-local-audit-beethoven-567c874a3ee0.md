PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-567c874a3ee0
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
    `567c874a3ee0b44cac77d94b96a7fde8c5eed11c18901ebbb7fdb02240bf1547`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "master",
        "change_count": 200,
        "changes_digest": "3c52653889eb2e65245cda94224a86b6190c673c48f7c76761b1b43d7663aefc",
        "changes_sample": [
          ".orch/recovery-ledger-16041039dfad.json",
          ".orch/recovery-ledger-55acd60c.json",
          ".orch/recovery-ledger-671c267eedf3.json",
          ".orch/recovery-ledger-6c8911116873.json",
          ".orch/recovery-ledger-7b6f925e1e7a.json",
          ".orch/recovery-ledger-7bd5c9d0be16.json",
          ".orch/recovery-ledger-85d2de79.json",
          ".orch/recovery-ledger-8d0702cbd5aa.json",
          ".orch/recovery-ledger-ca93a1b7be55.json",
          ".orch/recovery-ledger-e0945946bd0d.json",
          ".orch/recovery-ledger-ee86a2cff698.json",
          ".orch/recovery-ledger-fa219072749e.json",
          "HOLD-PROMPT-apparently-coverage-audit.md",
          "HOLD-PROMPT-apparently-harvey-parity.md",
          "HOLD-PROMPT-apparently-law-expert-network.md",
          "HOLD-PROMPT-apparently-treasury-tab.md",
          "HOLD-PROMPT-beethoven-madeus-platform.md",
          "HOLD-PROMPT-pareto-apparently-treasury.md",
          "HOLD-PROMPT-tomorrow-credit-rails-v2.md",
          "PROMPT-apparently-coverage-audit.md",
          "PROMPT-apparently-harvey-parity.md",
          "PROMPT-apparently-law-expert-network.md",
          "PROMPT-apparently-treasury-tab.md",
          "PROMPT-beethoven-madeus-platform.md",
          "PROMPT-pareto-apparently-treasury.md",
          "PROMPT-tomorrow-credit-rails-v2.md",
          "SPEC_RESOLVED-session-proof-of-work.md",
          "docs/chatgpt-local-reconcile-beethoven-7bd5c9d0be16.md",
          "docs/contract-routing.md",
          "docs/decisions/ADR-2026-08-08-5b3f0660-88c2-43ff-8928-5d85aaf023ef.md"
        ],
        "changes_total": 100,
        "head": "82b15bc0958f5fffd2a6bd3bcc30899872ef213a",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787105298,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
