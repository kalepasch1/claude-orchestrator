PROJECT: pareto-2080

- id: chatgpt-local-reconcile-pareto-2080-7c56b72c3c43
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
    `7c56b72c3c43343bc2a84e25b93efc29bc1f892f6b772c375f93de12ddbe4810`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 167,
        "items_digest": "c2b1bff7eb55b495df9d4063c743060a074cd1dca9ebf23b05715f756e5f9843",
        "items_sample": [
          {
            "created_at": 1785715438,
            "ref": "refs/orch-rescue/20260803T000634-2080",
            "sha": "d370931770b0bf541803d79d31c3828962c6e947",
            "subject": "fix(p0): provision Profiles on first login \u2014 the app was unusable for every real new user"
          },
          {
            "created_at": 1785715438,
            "ref": "refs/orch-rescue/20260803T000735-2080",
            "sha": "d370931770b0bf541803d79d31c3828962c6e947",
            "subject": "fix(p0): provision Profiles on first login \u2014 the app was unusable for every real new user"
          },
          {
            "created_at": 1785718612,
            "ref": "refs/orch-rescue/20260803T005652-economic-scheduler-revenue-3208fcb2",
            "sha": "3208fcb2366d643e784abe33deb5b10b4fb76cb7",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785726493,
            "ref": "refs/orch-rescue/20260803T030813-orch-config-consumption-75f8355d",
            "sha": "75f8355d7a2a2a9648ab08cd3f0d03358b4f1f09",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785758561,
            "ref": "refs/orch-rescue/20260803T124445-2080-6416da20",
            "sha": "6416da20132d84f2b7a24e6923514df5389272e2",
            "subject": "Merge remote-tracking branch 'origin/main'"
          },
          {
            "created_at": 1785801388,
            "ref": "refs/orch-rescue/20260803T235628-economic-scheduler-revenue-ae986e49",
            "sha": "ae986e499d4ded6bdf7a5ea84022d1d10a677cbb",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785802090,
            "ref": "refs/orch-rescue/20260804T000848-2080-fe8d1e61",
            "sha": "fe8d1e617a610caa0b112f7e535057249f14831f",
            "subject": "Merge branch 'agent/shadow-f52d31ee-cowork' (auto-resolved)"
          },
          {
            "created_at": 1785802464,
            "ref": "refs/orch-rescue/20260804T001424-ext-streaming-terms-49ab2694",
            "sha": "49ab269447d24c4fc93b5a0fb923577cebc362cc",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785802854,
            "ref": "refs/orch-rescue/20260804T002222-2080-60915add",
            "sha": "60915adda50ac8781683ad3f2873ab2a5c53f035",
            "subject": "Merge branch 'agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db' (auto-resolved)"
          },
          {
            "created_at": 1785802854,
            "ref": "refs/orch-rescue/20260804T030550-regen-qafix-pareto-2080-07222359-60915add",
            "sha": "60915adda50ac8781683ad3f2873ab2a5c53f035",
            "subject": "Merge branch 'agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db' (auto-resolved)"
          },
          {
            "created_at": 1785814696,
            "ref": "refs/orch-rescue/20260804T033817-pinned-express-lane-07584068",
            "sha": "07584068e6042035b15c7bc0d2c5fe8e83a1e495",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785814698,
            "ref": "refs/orch-rescue/20260804T033818-smarter-5-95-83fc9096",
            "sha": "83fc90964b5c7ba68cd25dd393c8d9b19ed2da18",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785818992,
            "ref": "refs/orch-rescue/20260804T045025-2080-39a3ea7e",
            "sha": "39a3ea7ec362ee4dfc0794c8576a59def279c591",
            "subject": "Merge branch 'recover-missing-branch-gate-esm-cjs-guard-slice-2' (continuous-merger)"
          },
          {
            "created_at": 1785802854,
            "ref": "refs/orch-rescue/20260804T045647-relfix-pareto-2080-07171927-verify-release-verify-vercel-deployment-60915add",
            "sha": "60915adda50ac8781683ad3f2873ab2a5c53f035",
            "subject": "Merge branch 'agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db' (auto-resolved)"
          },
          {
            "created_at": 1785819677,
            "ref": "refs/orch-rescue/20260804T050117-relfix-pareto-2080-07171927-verify-release-verify-vercel-deployment-e45426ae",
            "sha": "e45426aeeeccb8c061d1949813508d8399e71a05",
            "subject": "On agent/relfix-pareto-2080-07171927-verify-release-verify-vercel-deployment: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785820387,
            "ref": "refs/orch-rescue/20260804T051314-2080-c17aec6e",
            "sha": "c17aec6e25a124ba78332635bd48db4c161128d3",
            "subject": "Merge branch 'recover-missing-branch-fix-quarantine-invariant-slice-3' (continuous-merger)"
          },
          {
            "created_at": 1785821384,
            "ref": "refs/orch-rescue/20260804T052944-relfix-pareto-2080-07171927-verify-release-run-integration-and-e2e-tests-1b54d4c8",
            "sha": "1b54d4c88a2998a71dfc2746ec940829478dfd45",
            "subject": "On agent/relfix-pareto-2080-07171927-verify-release-run-integration-and-e2e-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785821697,
            "ref": "refs/orch-rescue/20260804T053457-relfix-pareto-2080-07171927-verify-release-run-integration-and-e2e-tests-c4798e0f",
            "sha": "c4798e0f4c81c888e6337fb1b0d437b4d8620180",
            "subject": "On agent/relfix-pareto-2080-07171927-verify-release-run-integration-and-e2e-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785849723,
            "ref": "refs/orch-rescue/20260804T133356-2080-b8baae48",
            "sha": "b8baae4818b25da109e39eb8fa42a0e93476e57d",
            "subject": "Merge branch 'agent/relfix-pareto-2080-07171927-verify-release-verify-merge-integrity' (auto-resolved)"
          },
          {
            "created_at": 1785858165,
            "ref": "refs/orch-rescue/20260804T154342-2080-11ddc0e9",
            "sha": "11ddc0e920c210490aa7244172008412c6f1ea4f",
            "subject": "Merge branch 'agent/qafix-pareto-2080-07240134-fix-dependency-readiness-issue' (auto-resolved)"
          },
          {
            "created_at": 1785862903,
            "ref": "refs/orch-rescue/20260804T170143-hive-arbitrage-enforcement-hook-edeadc15",
            "sha": "edeadc1547370f63d5cdcbd5c3a33cfd248afebb",
            "subject": "On agent/hive-arbitrage-enforcement-hook: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785862903,
            "ref": "refs/orch-rescue/20260804T170143-hive-enforcement-velocity-index-3683b3ce",
            "sha": "3683b3ce64f1a753d0497ca5b6f39c47a2884819",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785865519,
            "ref": "refs/orch-rescue/20260804T174909-2080-3a497d92",
            "sha": "3a497d92f2272b4ad152d1b2e2b2b1d4a22bf343",
            "subject": "Merge branch 'agent/relfix-pareto-2080-07171927-resolve-conflict-resolve-remaining-conflicts-playboo' (auto-resolved)"
          },
          {
            "created_at": 1785869547,
            "ref": "refs/orch-rescue/20260804T185451-2080-4d254a6b",
            "sha": "4d254a6bae200dc7d7787117b25caae886308f07",
            "subject": "feat(insights): ship tier-gated track-record surface at /insights/accuracy"
          },
          {
            "created_at": 1785870154,
            "ref": "refs/orch-rescue/20260804T191000-2080-17565f77",
            "sha": "17565f77f29a0920993342493cef9137317efcdb",
            "subject": "fix(insights): render /insights/accuracy without the default layout"
          },
          {
            "created_at": 1785891798,
            "ref": "refs/orch-rescue/20260805T010319-2080-38099d02",
            "sha": "38099d021c98bbbe9956f795bee7699ad021cdaa",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785892733,
            "ref": "refs/orch-rescue/20260805T012825-2080-d65fd85f",
            "sha": "d65fd85f81c41b68e691119e6eb82bf03bb25fff",
            "subject": "fix(treasury): create missing treasury_trust_lane table"
          },
          {
            "created_at": 1785921079,
            "ref": "refs/orch-rescue/20260805T091119-ploeh-s2s-bridge-tomorrow-5d3a519a",
            "sha": "5d3a519a3998b6fd82daa468bd5e9fcf095a991d",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785927529,
            "ref": "refs/orch-rescue/20260805T110517-2080-9557fb92",
            "sha": "9557fb92879ce076e9eb8f9244f763d334550786",
            "subject": "Merge branch 'agent/relfix-pareto-2080-07171927-verify-release-validate-vercel-deployment-readiness' (auto-resolved)"
          },
          {
            "created_at": 1785939214,
            "ref": "refs/orch-rescue/20260805T141516-2080-92150977",
            "sha": "921509771b2718aee21f734cb43d0aefc2c1fb67",
            "subject": "Merge branch 'agent/qafix-pareto-2080-07240134-fix-fdic-spreading-endpoint' (auto-resolved)"
          }
        ],
        "items_total": 167,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/pareto/2080"
      }
    ]
