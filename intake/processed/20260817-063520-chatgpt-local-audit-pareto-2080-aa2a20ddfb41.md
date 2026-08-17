PROJECT: pareto-2080

- id: chatgpt-local-reconcile-pareto-2080-aa2a20ddfb41
  title: Reconcile local ChatGPT/Codex build evidence for pareto-2080
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
    `aa2a20ddfb41443f8d18046cffa0692288ec513adf80493675864d756da24ba4`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786920973,
            "ref": "agent/cade-mirror-negotiation",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/contracts-smarter",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/orch-config-consumption",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/orch-cross-project-depends",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/prompt-evolution-bandit",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786672998,
            "ref": "agent/recover-missing-branch-qafix-pareto-2080-07062319-slice-1-slice-4-inspect-local-branches",
            "sha": "9a88a84e66826b6b05a5c33b6a60b79f2306d0bd",
            "subject": "build: dedupe vue via npm overrides to fix Nitro trace recursion"
          },
          {
            "committed_at": 1786832087,
            "ref": "agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2",
            "sha": "b49c9ca93ffa78d0c7c121a08b10ddce0ee23cb9",
            "subject": "agent: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/session-proof-of-work",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          },
          {
            "committed_at": 1786920973,
            "ref": "agent/smarter-5-95",
            "sha": "988fe03ca30d7b95ac5d527ce65f12f6ab903e31",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-pareto-2080-3de6b199d775' (auto-resolved)"
          }
        ],
        "count": 18,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/pareto/2080"
      }
    ]
