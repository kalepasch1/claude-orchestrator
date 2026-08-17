PROJECT: santas-secret-workshop

- id: chatgpt-local-reconcile-santas-secret-workshop-e2495fa48394
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
    `e2495fa483942f84b6cbca204611b8e8ed2d7895380d4de7230d568b4f1048a5`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
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
            "committed_at": 1786838645,
            "ref": "agent/chatgpt-local-reconcile-santas-secret-workshop-213-slice-1",
            "sha": "7d297ce00c185bb4a52ad736258346ecd5688e77",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-santas-secret-workshop-213-slice-1"
          },
          {
            "committed_at": 1786108646,
            "ref": "agent/consensus-engine-spec-fix-auto-filer-409-handler",
            "sha": "a89ad6dc12c1c64c0f130df80a3c10702ad522a5",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pri-slice-4' (auto-resolved)"
          },
          {
            "committed_at": 1786678911,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable",
            "sha": "f597405084fa876079bfd5c339e6e0096871dd85",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pri-slice-4' (auto-resolved)"
          },
          {
            "committed_at": 1786829036,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-single-supervisor",
            "sha": "7ffef20076142bcab2ec4f598cc7420cc35b51b9",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-santas-secret-workshop-213e212014e2' (auto-resolved)"
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
            "committed_at": 1786838284,
            "ref": "agent/orch-config-consumption",
            "sha": "acbf58af69d36e7e0cb97d20b6f00c14fc1b7358",
            "subject": "Merge branch 'agent/rework-secret-relfix-santas-secret-workshop-08151650-4a38f10' (auto-resolved)"
          },
          {
            "committed_at": 1786805768,
            "ref": "agent/relfix-santas-secret-workshop-08151152",
            "sha": "e6efb78c6749cac9cf4120d70696716707e58b6f",
            "subject": "agent: chatgpt-local-reconcile-santas-secret-workshop-1deead40e4a1 \u2014 verified ledger, 42 items, 0 unknown"
          },
          {
            "committed_at": 1786835567,
            "ref": "agent/relfix-santas-secret-workshop-08151650",
            "sha": "ec5cfef9d6adb64e8bb002c5cf7f70368567e522",
            "subject": "relfix: reconcile diverged production (master) into release-fix branch"
          },
          {
            "committed_at": 1786108655,
            "ref": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
            "sha": "2b6c00c21bd4110470c79ad4e9d6e5bc691f8c65",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pricing-earnable-free-group-2' (auto-resolved)"
          },
          {
            "committed_at": 1786835932,
            "ref": "agent/rework-secret-relfix-santas-secret-workshop-08151152-6bbca4a",
            "sha": "48f9a0c3455203eb6c647f2196b7f9976ccd0635",
            "subject": "Merge branch 'orchestrator/dev' into agent/rework-secret-relfix-santas-secret-workshop-08151152-6bbca4a"
          },
          {
            "committed_at": 1786818014,
            "ref": "backup/orchestrator-dev-pre-authorfix-08151650",
            "sha": "b406dbabe5e4213641998a9cfa8ee9d90c2b08db",
            "subject": "release-train: refresh orchestrator/dev from origin/master"
          },
          {
            "committed_at": 1786838284,
            "ref": "master",
            "sha": "acbf58af69d36e7e0cb97d20b6f00c14fc1b7358",
            "subject": "Merge branch 'agent/rework-secret-relfix-santas-secret-workshop-08151650-4a38f10' (auto-resolved)"
          },
          {
            "committed_at": 1786805768,
            "ref": "tmp-authorfix",
            "sha": "4196bdbbdf748c84318bb2a96656cba20d48962e",
            "subject": "agent: chatgpt-local-reconcile-santas-secret-workshop-1deead40e4a1 \u2014 verified ledger, 42 items, 0 unknown"
          }
        ],
        "count": 16,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/hisanta"
      }
    ]
