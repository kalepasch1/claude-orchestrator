PROJECT: santas-secret-workshop

- id: chatgpt-local-reconcile-santas-secret-workshop-e3d48aa0ff62
  title: Reconcile local ChatGPT/Codex build evidence for santas-secret-workshop
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
    `e3d48aa0ff62180a3a5352d56c292566b703ca8258093ccbd4ca5aad58bf6103`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/cade-mirror-negotiation",
        "change_count": 105,
        "changes_digest": "420e32ad09034c61089bf14321286a286bf702507ac8e297d3e82635c20de4a0",
        "changes_sample": [
          ".recovery-intent-canary-santas-secret-workshop-20260729.txt",
          ".recovery-intent-chatgpt-local-reconcile-santas-secret-workshop-9631ce317256.txt",
          ".recovery-intent-improve-common-brain-gamified-advent-experience-engine.txt",
          ".recovery-intent-qafix-santas-secret-workshop-08071303.txt",
          ".recovery-intent-remediate-botfix-santas-secret-workshop-865755-slice-1.txt",
          ".recovery-intent-remediate-botfix-santas-secret-workshop-865755-slice-3.txt",
          ".recovery-intent-remediate-botfix-santas-secret-workshop-865755-slice-4.txt",
          ".recovery-intent-remediate-botfix-santas-secret-workshop-865755.txt",
          ".recovery-intent-v15-27-rollout-hisanta.txt",
          ".ssw-bot-log.md",
          "BACKLOG_AUDIT_COMPLETE.md",
          "BACKLOG_COMPLETE_VERIFIED.md",
          "BACKLOG_COMPLETION_FINAL.md",
          "BACKLOG_COMPLETION_STATUS.txt",
          "BACKLOG_FINAL_VERIFICATION.md",
          "BACKLOG_FINAL_VERIFICATION_COMPLETE.md",
          "BACKLOG_SESSION.md",
          "IMPLEMENTATION_COMPLETE.md",
          "NEXT_STEPS.md",
          "REMEDIATION_SUMMARY.md",
          "STRATEGY_10X_MOAT.md",
          "app.json",
          "app/(auth)/_layout.tsx",
          "app/(auth)/forgot-password.tsx",
          "app/(auth)/invite/[code].tsx",
          "app/(auth)/login.tsx",
          "app/(auth)/signup.tsx",
          "app/(family)/_layout.tsx",
          "app/(family)/advent.tsx",
          "app/(family)/ai-log.tsx"
        ],
        "changes_total": 100,
        "head": "6a62cbb9bb72b852893916031a25b727d39d938c",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/hisanta-wt/cade-mirror-negotiation"
      }
    ]
