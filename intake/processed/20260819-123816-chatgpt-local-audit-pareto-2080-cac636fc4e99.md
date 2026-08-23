PROJECT: pareto-2080

- id: chatgpt-local-reconcile-pareto-2080-cac636fc4e99
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
    `cac636fc4e99940343af1f39dc26322088d10a7f38511bd5936fc8603a0a9eec`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 198,
        "items_digest": "0c690350972b6d4d148326bed33dbc44742c6827498e97f002264d34bbbc5e52",
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
          },
          {
            "created_at": 1785939502,
            "ref": "refs/orch-rescue/20260805T144054-2080-eece0ac7",
            "sha": "eece0ac79ada4b410eb80627afa14a37f735211c",
            "subject": "feat(landing): server-rendered public landing at /, cinematic montage moved to /story"
          },
          {
            "created_at": 1785941658,
            "ref": "refs/orch-rescue/20260805T145552-2080-d34d6d46",
            "sha": "d34d6d469cbe5bf17258a760f9b57e2b362f67ff",
            "subject": "Merge branch 'agent/recover-missing-branch-fix-quarantine-invariant-slice-5' (auto-resolved)"
          },
          {
            "created_at": 1785944255,
            "ref": "refs/orch-rescue/20260805T154505-2080-77491601",
            "sha": "774916015244fda636962f32031dc52dfa4da06c",
            "subject": "feat(story): server-rendered text layer and full SEO for /story"
          },
          {
            "created_at": 1785944952,
            "ref": "refs/orch-rescue/20260805T155213-2080-3fe71dee",
            "sha": "3fe71dee95bc73deec151bc9825ec8ef62a25df3",
            "subject": "Merge branch 'agent/recover-missing-branch-fix-quarantine-invariant-slice-4-prepare-for-integration' (auto-resolved)"
          },
          {
            "created_at": 1785945214,
            "ref": "refs/orch-rescue/20260805T155815-2080-336491e5",
            "sha": "336491e5daf709b9826c09b23feede531c4adc64",
            "subject": "fix(seo): serve a real sitemap.xml and robots.txt"
          },
          {
            "created_at": 1785948380,
            "ref": "refs/orch-rescue/20260805T165220-2080-1623f5ba",
            "sha": "1623f5bac0479f80d5835f7be3c013853986029d",
            "subject": "Merge branch 'agent/dropbox-wave-f-universal-coverage-doctrine-kill-the-silence-reads-as-contracts' (auto-resolved)"
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
          }
        ],
        "items_total": 198,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/pareto/2080"
      },
      {
        "count": 11,
        "items": [
          {
            "created_at": 1785327985,
            "ref": "stash@{0}",
            "sha": "eb91eabb81460fd8984c9413cbfbbdcde18cc024",
            "subject": "WIP on main: 18aba45 fix: replace bg-white/3 with bg-white/5 (invalid Tailwind opacity)"
          },
          {
            "created_at": 1784956957,
            "ref": "stash@{1}",
            "sha": "8e161aa126b1f139d1c59149f9b72851c943dcee",
            "subject": "WIP on main: ce4f9c8 Add personal.json stub to fix serverless function initialization"
          },
          {
            "created_at": 1784879115,
            "ref": "stash@{2}",
            "sha": "29a2b38a2dc31c33fb6cb76c1b821934e4b8d80d",
            "subject": "WIP on agent/fix-remaining-engine-tests-fix-money-velocity-and-mega-backdoor-rot: ac2c671 fix: moneyVelocity import path + megaBackdoorRoth 2025 IRS limits"
          },
          {
            "created_at": 1784860083,
            "ref": "stash@{3}",
            "sha": "60472267b81a867e647b722b925b326b4a7cb500",
            "subject": "WIP on main: 55ea901 feat: activate household intelligence and CADE panel"
          },
          {
            "created_at": 1784684649,
            "ref": "stash@{4}",
            "sha": "cda225ee8904cdec2ef369480d97ff1a367391c6",
            "subject": "On main: pre-force-merge"
          },
          {
            "created_at": 1784416759,
            "ref": "stash@{5}",
            "sha": "8c75777029212eeb12915f1a7a61a1d06257b7e7",
            "subject": "WIP on agent/recover-missing-branch-pricing-grid-reconstruction-slice-5: b53b4c1 agent: recover-missing-branch-pricing-grid-reconstruction-slice-5"
          },
          {
            "created_at": 1784177653,
            "ref": "stash@{6}",
            "sha": "05397f1a3ba648843465da7ce6cbcf0cabb6a6e0",
            "subject": "WIP on recovery/concurrent-primary-20260715-pareto: 97e78a3 recovery: preserve final Pareto source state"
          },
          {
            "created_at": 1784138565,
            "ref": "stash@{7}",
            "sha": "24a9077aca9b11b99556213d458253a6adff2e8e",
            "subject": "WIP on main: c4435d0 fix: resolve federated household identity"
          },
          {
            "created_at": 1783987002,
            "ref": "stash@{8}",
            "sha": "4160a395d345cc64595af2c19797ec9e115aaac1",
            "subject": "WIP on agent/recover-missing-branch-ci-writeback-gate-slice-3: b3574ff feat: add CSP frame-ancestors for orchestrator iframe"
          },
          {
            "created_at": 1783986650,
            "ref": "stash@{9}",
            "sha": "c4c3720d6307a6c60f706de7734726061e16977d",
            "subject": "On agent/recover-missing-branch-negative-space-optimizer-fix-annual-cost-usd-and-u-slice-5: manual-restore-1783986650"
          },
          {
            "created_at": 1783986595,
            "ref": "stash@{10}",
            "sha": "c6434e9de4b896a5d25f389b60d67485749b4e77",
            "subject": "On agent/recover-missing-branch-negative-space-optimizer-fix-annual-cost-usd-and-u-slice-5: manual-restore-1783986595"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/pareto/2080"
      }
    ]
