PROJECT: pareto-2080

- id: chatgpt-local-reconcile-pareto-2080-deb9bc597680
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
    `deb9bc597680ec629d63f4cb5076ef45070c99aec32769d83697c8bde4b84499`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 205,
        "items_digest": "afe3707d30fe9635243d12e13f720208676e1d34a70a355fcb85210bf6b19220",
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
            "created_at": 1785801388,
            "ref": "refs/orch-rescue/20260803T235628-economic-scheduler-revenue-ae986e49",
            "sha": "ae986e499d4ded6bdf7a5ea84022d1d10a677cbb",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785802464,
            "ref": "refs/orch-rescue/20260804T001424-ext-streaming-terms-49ab2694",
            "sha": "49ab269447d24c4fc93b5a0fb923577cebc362cc",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
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
            "created_at": 1785921079,
            "ref": "refs/orch-rescue/20260805T091119-ploeh-s2s-bridge-tomorrow-5d3a519a",
            "sha": "5d3a519a3998b6fd82daa468bd5e9fcf095a991d",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785948380,
            "ref": "refs/orch-rescue/20260805T203332-dropbox-pareto-2080-pareto-treasury-the-personal-cfo-layer-with-embe-fully-embedded-tomorrow-hedging-in-consumer-simp-1623f5ba",
            "sha": "1623f5bac0479f80d5835f7be3c013853986029d",
            "subject": "Merge branch 'agent/dropbox-wave-f-universal-coverage-doctrine-kill-the-silence-reads-as-contracts' (auto-resolved)"
          },
          {
            "created_at": 1785962416,
            "ref": "refs/orch-rescue/20260805T204017-wavef3-30f28a62",
            "sha": "30f28a623ee352d71f3f41e8924814be81dfc733",
            "subject": "On agent/dropbox-wave-f-universal-coverage-doctrine-kill-th-slice-3: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785967546,
            "ref": "refs/orch-rescue/20260805T220925-2080-c07459ab",
            "sha": "c07459abf294c716b2026baf66f4622d420b22e3",
            "subject": "perf(sync): keep investments sync inside the 300s function limit"
          },
          {
            "created_at": 1785972349,
            "ref": "refs/orch-rescue/20260805T232549-pinned-express-lane-ce558c35",
            "sha": "ce558c351241174d55aa57f6caddf4a2cf34fe84",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785976456,
            "ref": "refs/orch-rescue/20260806T003926-2080-710d78c0",
            "sha": "710d78c068a4fbfa2b745c77ba0d16c5b041090d",
            "subject": "Merge branch 'agent/relfix-pareto-2080-07171927-verify-release-run-integration-tests' (auto-resolved)"
          },
          {
            "created_at": 1785979399,
            "ref": "refs/orch-rescue/20260806T015710-2080-384c4345",
            "sha": "384c4345bb7bb56d75289451ec8283e054a732f9",
            "subject": "Merge branch 'agent/relfix-pareto-2080-07171927-resolve-conflict-analyze-conflict-and-plan' (auto-resolved)"
          },
          {
            "created_at": 1785984330,
            "ref": "refs/orch-rescue/20260806T024530-convention-conformance-lints-d2d38d91",
            "sha": "d2d38d9127af3abdcb06842d24dc17f4cfc368fd",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785984658,
            "ref": "refs/orch-rescue/20260806T025058-cade-mirror-negotiation-33377cdb",
            "sha": "33377cdb1f15eaa04ba045174d3dc4372403e210",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786013657,
            "ref": "refs/orch-rescue/20260806T105739-2080-cfd07e37",
            "sha": "cfd07e376a0bdb4d674627184c143aba54b0258b",
            "subject": "Merge branch 'agent/factory-unblock-rework-legal-qafix-pareto-2080-71110ec81a5b-ee0695d' (auto-resolved)"
          },
          {
            "created_at": 1786015036,
            "ref": "refs/orch-rescue/20260806T112001-2080-9980014b",
            "sha": "9980014b7222650cb2cf1968ed47c143e827df92",
            "subject": "Merge branch 'agent/rework-legal-qafix-pareto-2080-71110ec81a5b-ee0695d-adapt-pricinggridreconstruct' (auto-resolved)"
          },
          {
            "created_at": 1786015251,
            "ref": "refs/orch-rescue/20260806T112436-2080-60e25053",
            "sha": "60e2505348f336fe9f8995c50a7b3cd6772388bc",
            "subject": "Merge branch 'agent/rework-legal-qafix-pareto-2080-71110ec81a5b-ee0695d-refactor-codebase' (auto-resolved)"
          },
          {
            "created_at": 1786016870,
            "ref": "refs/orch-rescue/20260806T114834-2080-441881ab",
            "sha": "441881ab0bd43a40b5f6eaad12c03dd9f98377b5",
            "subject": "Merge branch 'agent/adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact' (auto-resolved)"
          },
          {
            "created_at": 1786016941,
            "ref": "refs/orch-rescue/20260806T115357-2080-0bd0b186",
            "sha": "0bd0b18612a4b7fb6a512a8c792274e5ff33b408",
            "subject": "Merge branch 'agent/qafix-pareto-2080-07240134-verify-collective-action-and-trust-utili' (auto-resolved)"
          },
          {
            "created_at": 1786017249,
            "ref": "refs/orch-rescue/20260806T115855-2080-9af4d161",
            "sha": "9af4d1617497c8e891846ebf67dc7625108ee6f7",
            "subject": "Merge branch 'agent/qafix-pareto-2080-71110ec81a5b-adapt-existing-implementation-analyze-patch-depen' (auto-resolved)"
          },
          {
            "created_at": 1786017737,
            "ref": "refs/orch-rescue/20260806T120514-2080-b5202f30",
            "sha": "b5202f305eefcebad35b9e52776ce368c6ebadbc",
            "subject": "Merge branch 'agent/qafix-pareto-2080-71110ec81a5b-adapt-existing-implementation-reconstruct-test-en' (auto-resolved)"
          },
          {
            "created_at": 1786019504,
            "ref": "refs/orch-rescue/20260806T123744-2080-a49fdb16",
            "sha": "a49fdb16172ba49066103230a916ab18e75ddc4b",
            "subject": "Merge branch 'agent/adversarial-second-opinion-split-the-build-task-in-slice-3-restore-missing-expor' (auto-resolved)"
          },
          {
            "created_at": 1786015251,
            "ref": "refs/orch-rescue/20260806T124831-canary-pareto-2080-20260726-update-build-script-60e25053",
            "sha": "60e2505348f336fe9f8995c50a7b3cd6772388bc",
            "subject": "Merge branch 'agent/rework-legal-qafix-pareto-2080-71110ec81a5b-ee0695d-refactor-codebase' (auto-resolved)"
          },
          {
            "created_at": 1786023387,
            "ref": "refs/orch-rescue/20260806T133627-rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db-443ea19c",
            "sha": "443ea19c5a84ef9ef45ea7eaf41e036b332f2efb",
            "subject": "On agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786023389,
            "ref": "refs/orch-rescue/20260806T133629-rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544-7dcb12ed",
            "sha": "7dcb12edaa9cb202f89a0c4495aab612c2ee8ad1",
            "subject": "On agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 205,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/pareto/2080"
      }
    ]
