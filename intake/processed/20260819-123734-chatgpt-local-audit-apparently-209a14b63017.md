PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-209a14b63017
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
    `209a14b630178b4c359dadd2816edbb1af11472d3b69416c10037f0accdc3469`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1785990738,
            "ref": "agent/backlog-batch-apparently-0ef7cd6-kpi-dashboard-recovery-implement-kpi-logic",
            "sha": "2d01e4879857ad42d1053c1f7718e43011541acc",
            "subject": "feat: integrate KPI metrics data layer into dashboard"
          },
          {
            "committed_at": 1785981089,
            "ref": "agent/hive-arbitrage-enforcement-hook",
            "sha": "5e6cc092f81598ef46ccf1d60e80dfc045637664",
            "subject": "agent: hive arbitrage enforcement hook \u2014 commit it, test it, fix the two bugs the tests found"
          },
          {
            "committed_at": 1786422029,
            "ref": "agent/illuminati-absorption-contracts",
            "sha": "2644606363fe093ca01baea7ddad02f4c9849d20",
            "subject": "agent: illuminati-absorption-contracts"
          },
          {
            "committed_at": 1786536013,
            "ref": "agent/reconcile-conflicts-72b7b924-be189d2d-focused-followup",
            "sha": "96f3e42f9d7b56a451d4f333ecd9da93d31c7360",
            "subject": "agent: reconcile-conflicts-72b7b924-be189d2d-focused-followup"
          },
          {
            "committed_at": 1787041109,
            "ref": "agent/v2-plan-intelligence-rail-and-renames",
            "sha": "a72ac81d68ecd567b94b5348cd1ec51b8aadb921",
            "subject": "agent: v2-plan-intelligence-rail-and-renames"
          },
          {
            "committed_at": 1787080834,
            "ref": "backup/pre-reauthor-20260818",
            "sha": "643d33c25689cb00a48eb76f173204d3d173b94d",
            "subject": "design(landing): pin at 1024x768 \u2014 the rail was taking a third of a small screen"
          },
          {
            "committed_at": 1785360970,
            "ref": "review/agent-access",
            "sha": "ef3370b6ef890031497f6ee936ee0c9a11cc2996",
            "subject": "test(hive): add shared-artifact-writes test suite"
          }
        ],
        "count": 7,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/apparently"
      }
    ]
