PROJECT: santas-secret-workshop

- id: chatgpt-local-reconcile-santas-secret-workshop-833d238f7e5c
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
    `833d238f7e5c6e1107ddc42a9e3a8ed7e87e95f2dd7a7321d42baf1db73d7b9c`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786677682,
            "ref": "agent/chatgpt-local-reconcile-santas-secret-workshop-c84-slice-1",
            "sha": "bedfe3d7d93bb028502d8a878c04e0ba359ea147",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-santas-secret-workshop-c84-slice-1"
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
            "committed_at": 1786108655,
            "ref": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
            "sha": "2b6c00c21bd4110470c79ad4e9d6e5bc691f8c65",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pricing-earnable-free-group-2' (auto-resolved)"
          },
          {
            "committed_at": 1786677682,
            "ref": "orchestrator/dev",
            "sha": "bedfe3d7d93bb028502d8a878c04e0ba359ea147",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-santas-secret-workshop-c84-slice-1"
          }
        ],
        "count": 7,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/hisanta"
      }
    ]
