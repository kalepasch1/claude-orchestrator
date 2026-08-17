PROJECT: pareto-2080

- id: chatgpt-local-reconcile-pareto-2080-4c3f70458a1e
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
    `4c3f70458a1eb674d5f87da09a0db81ee55b3787d400b1c6b6e3cc3f1248a6b0`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
            "committed_at": 1786938951,
            "ref": "agent/chatgpt-local-reconcile-pareto-2080-666dc7a62a3c",
            "sha": "9de2b5bd77ecd6d6e9af6f781a697cdfa353375e",
            "subject": "agent: chatgpt-local-reconcile-pareto-2080-666dc7a62a3c"
          },
          {
            "committed_at": 1786929464,
            "ref": "agent/chatgpt-local-reconcile-pareto-2080-8c0d5ec2f275",
            "sha": "5d3d54f0b1d98fc7040de7690b78a2e124b050fa",
            "subject": "agent: chatgpt-local-reconcile-pareto-2080-8c0d5ec2f275"
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
            "committed_at": 1786928965,
            "ref": "agent/dropbox-wave-f-universal-coverage-doctrine-kill-the-silence-reads-as-group-2-f1-",
            "sha": "28ed5b8766f2f376cb16b139f72c00db319c9d3b",
            "subject": "agent: dropbox-wave-f-universal-coverage-doctrine-kill-the-silence-reads-as-group-2-f1- (adoption path + 30-case suite)"
          },
          {
            "committed_at": 1786939413,
            "ref": "agent/dropbox-wave-f-universal-coverage-doctrine-kill-the-silence-reads-as-group-2-pri",
            "sha": "d2d187c2e6e14027786266caa49e590caa778d20",
            "subject": "agent: dropbox-wave-f-universal-coverage-doctrine-kill-the-silence-reads-as-group-2-pri \u2014 wire privilege-guard coverage to one denominator"
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
        "count": 19,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/pareto/2080"
      }
    ]
