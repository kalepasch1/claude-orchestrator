PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-377b03d6f0fa
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
    `377b03d6f0fa6d3a866f70ba60f135ca62d7e68a501bf7e175672100b9f4acfe`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/p1-postgrest-catch-misuse-remainder-20260812",
        "change_count": 54,
        "changes_digest": "61d43958ba83f77dd2c9a80f6f3002b59050d8004d4e0069e9c922b84ad18ec5",
        "changes_sample": [
          "server/api/admin/legal-opinion-portfolios.get.ts",
          "server/api/ai/task-graph.post.ts",
          "server/api/auth/smarter-handoff.post.ts",
          "server/api/cron/db-advisor-check.get.ts",
          "server/api/cron/weekly-digest.get.ts",
          "server/api/health-assessment/start.post.ts",
          "server/api/legal-opinions/[id]/deliverable.get.ts",
          "server/api/legal-opinions/[id]/deliverable/regenerate.post.ts",
          "server/api/legal-opinions/[id]/draft-response.post.ts",
          "server/api/legal-opinions/[id]/presence.post.ts",
          "server/api/legal-opinions/[id]/review-orchestrated.post.ts",
          "server/api/legal-opinions/[id]/review-v2.post.ts",
          "server/api/legal-opinions/[id]/review.get.ts",
          "server/api/legal-opinions/[id]/review.post.ts",
          "server/api/legal-opinions/[id]/risk-dashboard.get.ts",
          "server/api/legal-opinions/[id]/validate-flags.post.ts",
          "server/api/legal-opinions/index.post.ts",
          "server/api/license-os/adapter-prepare.post.ts",
          "server/api/license-os/orchestrate.post.ts",
          "server/api/metrics/summary.get.ts",
          "server/api/portal/session.get.ts",
          "server/api/promo/checkout.post.ts",
          "server/engines/_dormant/a2a-consultation.ts",
          "server/engines/_dormant/bot-correction-propagator.ts",
          "server/engines/_dormant/compliance-state-machine.ts",
          "server/engines/_dormant/promo-clause-manager.ts",
          "server/engines/a2a-consultation.ts",
          "server/engines/bot-correction-propagator.ts",
          "server/engines/compliance-ci/compliance-status.ts",
          "server/engines/compliance-state-machine.ts"
        ],
        "changes_total": 54,
        "head": "9f3d8221d896bd7e1cc9856db8f196309777cbf4",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786528693,
        "path": "/Users/kpasch/Documents/apparently-wt/p1pg"
      },
      {
        "branches": [
          {
            "committed_at": 1786455077,
            "ref": "agent/fabric-ledger-contract-index-20260811",
            "sha": "86e324cebc081f1583955b05ab1cb06b2652fdaf",
            "subject": "fix(fabric): unify jurisdiction ledger contract"
          },
          {
            "committed_at": 1786525269,
            "ref": "agent/p1-postgrest-catch-misuse-remainder-20260812",
            "sha": "9f3d8221d896bd7e1cc9856db8f196309777cbf4",
            "subject": "fix(template-loop): the 3-occurrence promotion path was unreachable"
          },
          {
            "committed_at": 1786454851,
            "ref": "landing-revamp-20260811",
            "sha": "c36c567aeba890a7fd926afb2bce1d4129cff766",
            "subject": "fix(landing): preserve intelligence and license surfaces"
          },
          {
            "committed_at": 1786525269,
            "ref": "orchestrator/dev",
            "sha": "9f3d8221d896bd7e1cc9856db8f196309777cbf4",
            "subject": "fix(template-loop): the 3-occurrence promotion path was unreachable"
          }
        ],
        "count": 4,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/apparently"
      }
    ]
