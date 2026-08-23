PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-a7f5bb34989f
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
    `a7f5bb34989fffd2ef3e1ca6afd3da6107ba540d9848a46a9114652e8f09a2ea`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "master",
        "change_count": 225,
        "changes_digest": "ffab89eb5fb8af1d0f8334aae260f4bbaa1cbc6dcdb2863056c43c83b2fba5ff",
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
          "SPEC-RUNNER-COUNTERFACTUAL-REPLAY.md",
          "SPEC_RESOLVED-session-proof-of-work.md",
          "docs/chatgpt-local-reconcile-beethoven-7bd5c9d0be16.md",
          "docs/contract-routing.md",
          "docs/decisions/ADR-2026-08-08-5b3f0660-88c2-43ff-8928-5d85aaf023ef.md",
          "docs/decisions/ADR-2026-08-08-8096ccb3-ed1e-417e-93ee-4cce4e0a2948.md",
          "docs/decisions/ADR-2026-08-08-business-model-check-regulatory-dropbox-tomorrow-foulkon-hed.md",
          "docs/decisions/ADR-2026-08-08-e4a29eee-59fe-4409-a9a0-cffe9c0cb53c.md",
          "docs/decisions/ADR-2026-08-08-f4c5fb8c-98c8-4784-a2d1-7db5d021fa54.md",
          "docs/decisions/ADR-2026-08-08-f879c3d4-d1bc-446f-ba0c-c22192ed3756.md",
          "docs/decisions/ADR-2026-08-11-business-model-check-regulatory-p1-product-integration-gaps-.md",
          "docs/decisions/ADR-2026-08-11-business-model-check-regulatory-part9-foresight-shadow-packs.md",
          "docs/decisions/ADR-2026-08-13-10f761a4-af79-4c51-8750-683bc2dc3257.md",
          "docs/decisions/ADR-2026-08-13-5cf16310-1131-472a-b470-ef38377957a5.md",
          "docs/decisions/ADR-2026-08-13-72fcfbef-fd9c-4319-a5c3-463658e43515.md",
          "docs/decisions/ADR-2026-08-13-bcbf1013-b0e4-49c7-a9a4-35e6ec51883a.md",
          "docs/decisions/ADR-2026-08-13-bdec4843-2077-4375-8791-49165a0aafb0.md",
          "docs/decisions/ADR-2026-08-14-90324165-ee8b-4f8f-a493-1908200c236e.md"
        ],
        "changes_total": 100,
        "head": "d500bc4acd1c493f0e46554f4287e2afadd4f70d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787173461,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
