PROJECT: kalepasch-com

- id: chatgpt-local-reconcile-kalepasch-com-c0e5e269ad4c
  title: Reconcile local ChatGPT/Codex build evidence for kalepasch-com
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
    `c0e5e269ad4c7e3d6d415527461c2007777201280b6aa6b85c0ff65df03d7fa8`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "main",
        "change_count": 1,
        "changes": [
          "current-events/feed.md"
        ],
        "changes_digest": "47e0b8d9bf4abad4992a7757ee17a8e2b279072ee7f3a8fb4897468220eb75bd",
        "head": "cef2b65f1af561a85438de194b28af4260dccd4e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786564192,
        "path": "/Users/kpasch/Documents/vinci"
      },
      {
        "branches": [
          {
            "committed_at": 1785852687,
            "ref": "agent/ploeh-s2s-bridge-tomorrow",
            "sha": "ffa1a2b46704397b824be90c0016863109eedae5",
            "subject": "Merge branch 'agent/relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-update-tests-checks' (auto-resolved)"
          },
          {
            "committed_at": 1785853713,
            "ref": "agent/relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-update-tests-checks",
            "sha": "71cd418ecf86a97fce668d4e681253446d92d534",
            "subject": "salvage: interrupted work for relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-update-tests-checks"
          },
          {
            "committed_at": 1785971316,
            "ref": "agent/relfix-kalepasch-com-da085f99f2ba-resolve-remaining-conflicts-manually",
            "sha": "08b29db7ad7df2665df59d61ec352cd40839b915",
            "subject": "salvage: interrupted work for relfix-kalepasch-com-da085f99f2ba-resolve-remaining-conflicts-manually"
          },
          {
            "committed_at": 1784761526,
            "ref": "safety/pre-canonical-deploy-20260722",
            "sha": "d3ec59f2bfbe5d42e7564404507a61b8e2222265",
            "subject": "Merge remote-tracking branch 'origin/main'"
          }
        ],
        "count": 4,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/smarter/pasch"
      },
      {
        "count": 1,
        "items": [
          {
            "created_at": 1784696963,
            "ref": "stash@{0}",
            "sha": "628a45ec5449647390b11ad2b3d46f7945e4e72c",
            "subject": "WIP on main: dd4f870 fix: use current Vigil and Triage marks"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/pasch"
      },
      {
        "count": 1,
        "items": [
          {
            "created_at": 1784686645,
            "ref": "stash@{0}",
            "sha": "af26c6e3a978bba35180ee5d706f548bceb4dc8f",
            "subject": "WIP on main: 796ae37 Add public authority and briefing surfaces"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/smarter/pasch"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/pasch",
        "routing": "kalepasch-com"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/vinci",
        "routing": "kalepasch-com"
      }
    ]
