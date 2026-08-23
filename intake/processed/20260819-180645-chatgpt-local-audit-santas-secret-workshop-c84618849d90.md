PROJECT: santas-secret-workshop

- id: chatgpt-local-reconcile-santas-secret-workshop-c84618849d90
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
    `c84618849d90e1dee7a8dd471cdf1011ad0c76addffa94d95ec12eab1d3c1243`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1787086878,
            "ref": "agent/approval-digest-batching",
            "sha": "4f4affe81dfa12294cfa018fe4f7a6a4d59d5428",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-santas-secret-workshop-b34b15c9faff' (auto-resolved)"
          },
          {
            "committed_at": 1786794178,
            "ref": "agent/chatgpt-local-reconcile-santas-secret-workshop-07259c5e5322",
            "sha": "a593a76c943cb535db164dfbffa0235cf71c47ad",
            "subject": "agent: chatgpt-local-reconcile-santas-secret-workshop-07259c5e5322"
          },
          {
            "committed_at": 1786805768,
            "ref": "agent/chatgpt-local-reconcile-santas-secret-workshop-1deead40e4a1",
            "sha": "e6efb78c6749cac9cf4120d70696716707e58b6f",
            "subject": "agent: chatgpt-local-reconcile-santas-secret-workshop-1deead40e4a1 \u2014 verified ledger, 42 items, 0 unknown"
          },
          {
            "committed_at": 1787067811,
            "ref": "agent/chatgpt-local-reconcile-santas-secret-workshop-c84-slice-3",
            "sha": "b6d311000c6542b5b3411d25dd716c4b47602549",
            "subject": "reconcile: resolve rebase conflict against orchestrator/dev for c84-slice-3"
          },
          {
            "committed_at": 1786108646,
            "ref": "agent/consensus-engine-spec-fix-auto-filer-409-handler",
            "sha": "a89ad6dc12c1c64c0f130df80a3c10702ad522a5",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pri-slice-4' (auto-resolved)"
          },
          {
            "committed_at": 1787066204,
            "ref": "agent/cont-5f9e0e",
            "sha": "2cf40965e37e536fdefc84f85738ec9c7b50cad9",
            "subject": "Merge branch 'agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544' (auto-resolved)"
          },
          {
            "committed_at": 1787086878,
            "ref": "agent/deployfix-darwn-vercel-1783343439",
            "sha": "4f4affe81dfa12294cfa018fe4f7a6a4d59d5428",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-santas-secret-workshop-b34b15c9faff' (auto-resolved)"
          },
          {
            "committed_at": 1786678911,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable",
            "sha": "f597405084fa876079bfd5c339e6e0096871dd85",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pri-slice-4' (auto-resolved)"
          },
          {
            "committed_at": 1786678926,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests",
            "sha": "33f60c91c6e5e9f8f088127076c88e29052fcf65",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pricing-earnable-free-group-2' (auto-resolved)"
          },
          {
            "committed_at": 1786678921,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter",
            "sha": "f1d3a729d2b519e92e3c350f659f8ba902dd0b4b",
            "subject": "Merge branch 'agent/consensus-engine-spec-fix-auto-filer-409-handler' (auto-resolved)"
          },
          {
            "committed_at": 1787086878,
            "ref": "agent/orch-config-consumption",
            "sha": "4f4affe81dfa12294cfa018fe4f7a6a4d59d5428",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-santas-secret-workshop-b34b15c9faff' (auto-resolved)"
          },
          {
            "committed_at": 1787086878,
            "ref": "agent/orch-cross-project-depends",
            "sha": "4f4affe81dfa12294cfa018fe4f7a6a4d59d5428",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-santas-secret-workshop-b34b15c9faff' (auto-resolved)"
          },
          {
            "committed_at": 1787086878,
            "ref": "agent/prompt-evolution-bandit",
            "sha": "4f4affe81dfa12294cfa018fe4f7a6a4d59d5428",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-santas-secret-workshop-b34b15c9faff' (auto-resolved)"
          },
          {
            "committed_at": 1786805768,
            "ref": "agent/relfix-santas-secret-workshop-08151152",
            "sha": "e6efb78c6749cac9cf4120d70696716707e58b6f",
            "subject": "agent: chatgpt-local-reconcile-santas-secret-workshop-1deead40e4a1 \u2014 verified ledger, 42 items, 0 unknown"
          },
          {
            "committed_at": 1786920393,
            "ref": "agent/relfix-santas-secret-workshop-08151843",
            "sha": "7b601feecf0d5c5cd107e91c66e2de3daf6e83dc",
            "subject": "relfix: merge origin/master (5dd55308) to reconcile staging/prod divergence"
          },
          {
            "committed_at": 1786108655,
            "ref": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
            "sha": "2b6c00c21bd4110470c79ad4e9d6e5bc691f8c65",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pricing-earnable-free-group-2' (auto-resolved)"
          },
          {
            "committed_at": 1786818014,
            "ref": "backup/orchestrator-dev-pre-authorfix-08151650",
            "sha": "b406dbabe5e4213641998a9cfa8ee9d90c2b08db",
            "subject": "release-train: refresh orchestrator/dev from origin/master"
          },
          {
            "committed_at": 1787086878,
            "ref": "master",
            "sha": "4f4affe81dfa12294cfa018fe4f7a6a4d59d5428",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-santas-secret-workshop-b34b15c9faff' (auto-resolved)"
          },
          {
            "committed_at": 1786805768,
            "ref": "tmp-authorfix",
            "sha": "4196bdbbdf748c84318bb2a96656cba20d48962e",
            "subject": "agent: chatgpt-local-reconcile-santas-secret-workshop-1deead40e4a1 \u2014 verified ledger, 42 items, 0 unknown"
          }
        ],
        "count": 19,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/hisanta"
      }
    ]
