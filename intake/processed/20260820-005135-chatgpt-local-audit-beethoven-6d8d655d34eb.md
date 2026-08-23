PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-6d8d655d34eb
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
    `6d8d655d34eb3a5b6b47b39ea85d34736a719d4d0f22df606acbd37c44203031`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 1,
        "changes": [
          "packages/spine/package-lock.json"
        ],
        "changes_digest": "46a7918e82268ce256c4b5a81d6fa95fe57b826dc125bb7a3d75caaccd593873",
        "head": "987e5280e7bf2c0f7e0d598c9ddadc40daec714e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786578520,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/spine-types-x2"
      },
      {
        "count": 4,
        "items": [
          {
            "created_at": 1787040393,
            "ref": "stash@{0}",
            "sha": "9837583420a894d85e4c8a7d8bfab49679d4135a",
            "subject": "On agent/orch-cross-project-depends: sentinel-drift-agent/orch-cross-project-depends-1787040335"
          },
          {
            "created_at": 1787039997,
            "ref": "stash@{1}",
            "sha": "80740fe5fd5fa00007f76d9f28fe11e514673a73",
            "subject": "WIP on master: 527f1ef0 Fix: resource_governor \u2014 convert frozen module constants to live env-var reads so fleet_control tuning changes take effect without restart"
          },
          {
            "created_at": 1787026208,
            "ref": "stash@{2}",
            "sha": "a9f38fd798b8ffbffb9725191bfb66c90ac77187",
            "subject": "WIP on master: 2acd4139 Add comprehensive tests for opportunity_scout.py RICE scoring and proposal filing"
          },
          {
            "created_at": 1787011491,
            "ref": "stash@{3}",
            "sha": "6ca51b977b01731c37d8e975f4015ba3aff66a28",
            "subject": "WIP on master: e5c6c5bf docs: top 3 highest-leverage opportunities from runner codebase scan (RICE-scored)"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      },
      {
        "branches": [
          {
            "committed_at": 1786465525,
            "ref": "chatgpt/chatgpt-local-intake-receipt-safety-20260811-08111725",
            "sha": "30f1b581b055fe14160d2398c47717d98eaffcf4",
            "subject": "chore: apply claude-orchestrator--chatgpt-local-intake-receipt-safety-20260811 (via chatgpt-bridge)"
          },
          {
            "committed_at": 1786492386,
            "ref": "chatgpt/chatgpt-local-queue-bridge-20260811-08111602",
            "sha": "cab66e31b3246c483d5ff753dd5f4a21816aadf6",
            "subject": "fix: serialize local audit registry writers"
          },
          {
            "committed_at": 1786496637,
            "ref": "chatgpt/operator-output-truth-session-fabric-20260812-08120203",
            "sha": "8e22697a6ec8b444ff667a501d7a1669658d9126",
            "subject": "fix(orchestrator): expose delivery truth and fence stale runners"
          },
          {
            "committed_at": 1787008555,
            "ref": "chatgpt/promotion-and-funnel-fixes-20260817-08171915",
            "sha": "591164052780473c7f65864ef2ced240f248e9c1",
            "subject": "ci: put the three new guard suites inside the blocking gate"
          },
          {
            "committed_at": 1787009829,
            "ref": "chatgpt/promotion-funnel-and-prod-urls-20260817-08171936",
            "sha": "41f302b7f4cc4a2a9168a0a7d5f6c1de71f3ebfc",
            "subject": "fix(release-health): two prod_urls were Vercel's login page, and the guard could not see it"
          },
          {
            "committed_at": 1787012761,
            "ref": "chatgpt/promotion-funnel-prod-urls-and-review-fixes-2026-08172022",
            "sha": "0293683202a74704c3b00556cd2e9c797faecfaa",
            "subject": "fix: four defects an adversarial review of my own diff found, three reproduced"
          },
          {
            "committed_at": 1786492554,
            "ref": "codex/pinned-claim-escape",
            "sha": "66b09cbc942767c695738de9d306d09b3babd9c1",
            "subject": "Make pinned tasks visible beyond claim scan cap"
          }
        ],
        "count": 7,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/Trojun-orchestrator-misclone-20260812",
        "routing": "beethoven"
      }
    ]
