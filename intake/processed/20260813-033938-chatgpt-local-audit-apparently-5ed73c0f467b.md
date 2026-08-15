PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-5ed73c0f467b
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
    `5ed73c0f467b1a3880cc03d0ae995af3cf316ad61a1ac5ab4b32c4c9bd918bf8`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
            "committed_at": 1786455077,
            "ref": "agent/fabric-ledger-contract-index-20260811",
            "sha": "86e324cebc081f1583955b05ab1cb06b2652fdaf",
            "subject": "fix(fabric): unify jurisdiction ledger contract"
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
            "committed_at": 1786454851,
            "ref": "landing-revamp-20260811",
            "sha": "c36c567aeba890a7fd926afb2bce1d4129cff766",
            "subject": "fix(landing): preserve intelligence and license surfaces"
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
