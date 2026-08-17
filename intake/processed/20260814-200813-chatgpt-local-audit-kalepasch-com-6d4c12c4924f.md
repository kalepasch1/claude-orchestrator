PROJECT: kalepasch-com

- id: chatgpt-local-reconcile-kalepasch-com-6d4c12c4924f
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
    `6d4c12c4924f01bf369d40371972c8c4567e5813567894ad5a891badcb75c964`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1785852687,
            "ref": "agent/ploeh-s2s-bridge-tomorrow",
            "sha": "ffa1a2b46704397b824be90c0016863109eedae5",
            "subject": "Merge branch 'agent/relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-update-tests-checks' (auto-resolved)"
          },
          {
            "committed_at": 1785912101,
            "ref": "agent/prompt-evolution-bandit",
            "sha": "83e7200892b92a7ec2f2e6887ce919a1d99a829c",
            "subject": "Merge branch 'agent/canary-kalepasch-com-20260731' (auto-resolved)"
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
        "count": 5,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/smarter/pasch"
      },
      {
        "count": 198,
        "items_digest": "97496305ef03646ab29ea217900e8b3d4f5e30151477de486df6a03d367672a0",
        "items_sample": [
          {
            "created_at": 1785709676,
            "ref": "refs/orch-rescue/20260803T000636-pasch",
            "sha": "ce9efa5c23f336520e5a36ae629f19b039cdb618",
            "subject": "Merge branch 'agent/relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-write-patch' (auto-resolved)"
          },
          {
            "created_at": 1785715597,
            "ref": "refs/orch-rescue/20260803T000637-cc-legacy-margin-removal",
            "sha": "50f3d860d41315582e6d29415cb82ca738154a78",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715597,
            "ref": "refs/orch-rescue/20260803T000637-cc-mutual-default-fund",
            "sha": "6b6ec40008609cfc234f09343c0c5ced23a5daca",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715598,
            "ref": "refs/orch-rescue/20260803T000638-convention-conformance-lints",
            "sha": "f796b886a6eb21114bdc3a96ba06ed22eab9f6c9",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715598,
            "ref": "refs/orch-rescue/20260803T000638-economic-scheduler-revenue",
            "sha": "b3c5afa02ae24df308e34c7b8834aa2daa616914",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715599,
            "ref": "refs/orch-rescue/20260803T000639-hive-enforcement-velocity-index",
            "sha": "c8ce8dd172f0bdf5a6b123d73a5b3db3d0d99bca",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715599,
            "ref": "refs/orch-rescue/20260803T000639-merged-diff-memory",
            "sha": "92be373196b5c07ee2034bd9e02d4c7eb249f0bb",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715599,
            "ref": "refs/orch-rescue/20260803T000639-orch-config-consumption",
            "sha": "d81c5f831200a9be12afdb6e1529a491fc6409c2",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715599,
            "ref": "refs/orch-rescue/20260803T000639-pinned-express-lane",
            "sha": "540b3650d8f80fec86ef8d133d0d00ff5bacdc91",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-ploeh-s2s-bridge-tomorrow",
            "sha": "b8db4dc8773244b25e039a141f0b62fb15f32adb",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-prompt-evolution-bandit",
            "sha": "3742ecd3843c6c155401eef89465b204b469692a",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-cc-legacy-margin-removal",
            "sha": "7c045d5d74fe393fd5e909fe4026d9e9966dd5d1",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-cc-mutual-default-fund",
            "sha": "79b97297788460050064b59b905fa219e7780bb7",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-convention-conformance-lints",
            "sha": "92dcc7f947413df943b43a37cf31f6c4c88e6242",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-economic-scheduler-revenue",
            "sha": "98bc7b8050a9dcb9d83dbee85cf26a81a01e9436",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-hive-enforcement-velocity-index",
            "sha": "867611db866768fb74739514f8524eec4fa028eb",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-merged-diff-memory",
            "sha": "b22c303672de565f548603f38bafcfe1c66ae26b",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-orch-config-consumption",
            "sha": "e09aa92b96b84bbb522e28ec6ffce3f33af35176",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-pasch",
            "sha": "5a4665f49d5bd032898d17d4396818582c5e3e63",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-pinned-express-lane",
            "sha": "fa47742993a0af41f76a11be1f138e067af286ff",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-ploeh-s2s-bridge-tomorrow",
            "sha": "b8cd451b800cccccf4778e92b863d806273c7ee1",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-prompt-evolution-bandit",
            "sha": "c22fe946bd9cef27d1370d7a2f4d0e4bebe52133",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716096,
            "ref": "refs/orch-rescue/20260803T001456-cc-legacy-margin-removal-41267fe0",
            "sha": "41267fe0a6157abd489579a1e5528c783b9accae",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716096,
            "ref": "refs/orch-rescue/20260803T001456-cc-mutual-default-fund-f3fd148d",
            "sha": "f3fd148d24a756b66a1cb992bc5be74cb11b84b7",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716096,
            "ref": "refs/orch-rescue/20260803T001456-convention-conformance-lints-a01e0c4a",
            "sha": "a01e0c4a016c9a0fb5d45bc829d3989af72838a1",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716096,
            "ref": "refs/orch-rescue/20260803T001456-pasch-0d9084c3",
            "sha": "0d9084c3bc57db0e82f46cf0e73aee45e3afd6e6",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716097,
            "ref": "refs/orch-rescue/20260803T001457-economic-scheduler-revenue-918cc860",
            "sha": "918cc86023758dafe0ae63aa928dc99b356f1804",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716097,
            "ref": "refs/orch-rescue/20260803T001457-hive-enforcement-velocity-index-1c8c563e",
            "sha": "1c8c563e996b745eb0e015edb9576d61ec23e6b2",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716097,
            "ref": "refs/orch-rescue/20260803T001457-merged-diff-memory-06c93286",
            "sha": "06c9328679afd3c797b79b5e9e0e3d96ff4f2889",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716097,
            "ref": "refs/orch-rescue/20260803T001457-orch-config-consumption-1e32ba03",
            "sha": "1e32ba03971049461920a805a5e67c834b413f4d",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 198,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/smarter/pasch"
      }
    ]
