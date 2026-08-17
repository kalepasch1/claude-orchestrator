PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-87d614f80b42
  title: Reconcile local ChatGPT/Codex build evidence for apparently
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
    `87d614f80b42acb9610da897a8d932908c275f4043472998875803d62b4ce920`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786455077,
            "ref": "agent/fabric-ledger-contract-index-20260811",
            "sha": "86e324cebc081f1583955b05ab1cb06b2652fdaf",
            "subject": "fix(fabric): unify jurisdiction ledger contract"
          },
          {
            "committed_at": 1786454851,
            "ref": "landing-revamp-20260811",
            "sha": "c36c567aeba890a7fd926afb2bce1d4129cff766",
            "subject": "fix(landing): preserve intelligence and license surfaces"
          },
          {
            "committed_at": 1786494401,
            "ref": "orchestrator/dev",
            "sha": "02e8490340ed364d56d99527c47010d817d214c4",
            "subject": "perf(ci): route dependency-free packages/** to a standalone tsconfig"
          }
        ],
        "count": 3,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/apparently"
      },
      {
        "count": 206,
        "items_digest": "5cc515f43e8f380afe3a7b6e667e8d8e05ea3a8b573fba5ba07277678921d7ae",
        "items_sample": [
          {
            "created_at": 1785715384,
            "ref": "refs/orch-rescue/20260803T000629-apparently",
            "sha": "820c18196a69f71d05d02188c78c9ade534d6cd7",
            "subject": "fix(p0): licensing chain end-to-end \u2014 requirement expansion, document attachment, real email submission"
          },
          {
            "created_at": 1785715592,
            "ref": "refs/orch-rescue/20260803T000632-a8a63f0482aed16feeac",
            "sha": "b6a1598d0a609a2a9a8848df3ecc1deab5937520",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715384,
            "ref": "refs/orch-rescue/20260803T000733-apparently",
            "sha": "820c18196a69f71d05d02188c78c9ade534d6cd7",
            "subject": "fix(p0): licensing chain end-to-end \u2014 requirement expansion, document attachment, real email submission"
          },
          {
            "created_at": 1785715654,
            "ref": "refs/orch-rescue/20260803T000734-a8a63f0482aed16feeac",
            "sha": "502d09ff3e2d0496522eaceee970a3dbb02fd809",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715384,
            "ref": "refs/orch-rescue/20260803T001451-apparently-820c1819",
            "sha": "820c18196a69f71d05d02188c78c9ade534d6cd7",
            "subject": "fix(p0): licensing chain end-to-end \u2014 requirement expansion, document attachment, real email submission"
          },
          {
            "created_at": 1785716095,
            "ref": "refs/orch-rescue/20260803T001455-a8a63f0482aed16feeac-588e56cc",
            "sha": "588e56ccd529b16df8cfa892ec1df38735578fd1",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717653,
            "ref": "refs/orch-rescue/20260803T004053-improve-common-brain-regulatory-determination-hive-c84d80ad",
            "sha": "c84d80ad73cac19f13a8105d2f34315cb723bf4a",
            "subject": "On agent/improve-common-brain-regulatory-determination-hive: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718202,
            "ref": "refs/orch-rescue/20260803T005246-apparently-7a47f50b",
            "sha": "7a47f50bff6978a99f284ebad143c4c6b043abcc",
            "subject": "fix(submissions): supply the missing preflight writer + repair the assemble gate"
          },
          {
            "created_at": 1785718367,
            "ref": "refs/orch-rescue/20260803T005247-convention-conformance-lints-334e69d5",
            "sha": "334e69d567b4ab789ad6db560ddc1d5df6f8d4c5",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785725113,
            "ref": "refs/orch-rescue/20260803T024513-a8a63f0482aed16feeac-4d14cf27",
            "sha": "4d14cf27bed51f7ed17a3e3c5cc96b24254ece10",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785727035,
            "ref": "refs/orch-rescue/20260803T031715-oc-autoclear-policy-2a78b587",
            "sha": "2a78b58777cf22f53e6cd5435d1da40102126f10",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785799774,
            "ref": "refs/orch-rescue/20260803T232934-cc-legacy-margin-removal-f6ee61b6",
            "sha": "f6ee61b6334b1f59f65346709a2630d251f5ce42",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785799775,
            "ref": "refs/orch-rescue/20260803T232935-cc-mutual-default-fund-2ab94763",
            "sha": "2ab94763050200b4220828fffb5e92546c0ebc83",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785799776,
            "ref": "refs/orch-rescue/20260803T232936-economic-scheduler-revenue-d80e2074",
            "sha": "d80e20747b540868ca65ee3498aed1c312b48a68",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785799776,
            "ref": "refs/orch-rescue/20260803T232936-hive-enforcement-velocity-index-4acd5f35",
            "sha": "4acd5f35a4879c48744524f522ca8291099efd65",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785799777,
            "ref": "refs/orch-rescue/20260803T232937-improve-mesh-apparently-regulatory-intelligence-ma-slice-5-add-or-update-test-lo-4459db46",
            "sha": "4459db4667757fe593c1063ad2f7a8422f75b2c3",
            "subject": "On agent/improve-mesh-apparently-regulatory-intelligence-ma-slice-5-add-or-update-test-lo: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785800646,
            "ref": "refs/orch-rescue/20260803T234406-hive-enforcement-velocity-index-877bc244",
            "sha": "877bc24458e3696ccb72bfa5efb8da33b89689a0",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785800647,
            "ref": "refs/orch-rescue/20260803T234407-merged-diff-memory-a3de3532",
            "sha": "a3de3532963fb342780046e8e168e3754c4803f0",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785800650,
            "ref": "refs/orch-rescue/20260803T234412-orch-config-consumption-ce44627a",
            "sha": "ce44627aec5b0978412286d75c4424e8afa31ceb",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785800655,
            "ref": "refs/orch-rescue/20260803T234416-pinned-express-lane-8fbfa342",
            "sha": "8fbfa342ac61e4638980a3d89b126a222d6536af",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785800660,
            "ref": "refs/orch-rescue/20260803T234421-prompt-evolution-bandit-77f21642",
            "sha": "77f21642b57cff94d15266e827d7dcfa40ee9f8b",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785810227,
            "ref": "refs/orch-rescue/20260804T022417-apparently-83bf57ff",
            "sha": "83bf57ffd987d14ba2233e3385e629347d96eb62",
            "subject": "Merge branch 'agent/backlog-batch-apparently-015d6d4-adapt-lint-code-adapt-lint-diffs-slice-4' (auto-resolved)"
          },
          {
            "created_at": 1785810722,
            "ref": "refs/orch-rescue/20260804T023226-apparently-1e428024",
            "sha": "1e428024d51dd9304fb1d3db9ccbd88664535d3a",
            "subject": "Merge branch 'agent/dropbox-apparently-merge-vigil-into-apparently-gaming-exams-for-all--13-protection-storefront-living-memo-funds-its-o' (auto-resolved)"
          },
          {
            "created_at": 1785811569,
            "ref": "refs/orch-rescue/20260804T024615-apparently-bf8a4e26",
            "sha": "bf8a4e26dbbdb70b158929fd8571f2bcd5e50fd0",
            "subject": "Merge branch 'agent/dropbox-vigil-apparently-gaming-regulator-portal-build-now-group-4' (auto-resolved)"
          },
          {
            "created_at": 1785811739,
            "ref": "refs/orch-rescue/20260804T025131-apparently-2737d0b8",
            "sha": "2737d0b836357bf021e5cd42f3e9a7ce09a5119b",
            "subject": "Merge branch 'agent/weekly-lint-apparently' (auto-resolved)"
          },
          {
            "created_at": 1785814083,
            "ref": "refs/orch-rescue/20260804T032803-breach-remediation-7a7c4898",
            "sha": "7a7c489835ee1273538eb83bc6e7eab1a112f64d",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785814083,
            "ref": "refs/orch-rescue/20260804T032803-cade-mirror-negotiation-c73df165",
            "sha": "c73df165537ba1bee7c990dfc2689203f7839f2d",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785814087,
            "ref": "refs/orch-rescue/20260804T032807-ploeh-s2s-bridge-tomorrow-cccf1a57",
            "sha": "cccf1a57853ac364c301bbef064b54ae34c1aac6",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785814756,
            "ref": "refs/orch-rescue/20260804T033916-causal-outcome-feedback-5a4d3ffb",
            "sha": "5a4d3ffbdab0d17d73bea9a73ab2e48d943f27f9",
            "subject": "On agent/causal-outcome-feedback: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785815988,
            "ref": "refs/orch-rescue/20260804T035948-improve-mesh-apparently-regulatory-intelligence-ma-slice-5-add-or-update-test-va-bb6b425b",
            "sha": "bb6b425b0b9ced5111df507c6061a060e12456ac",
            "subject": "On agent/improve-mesh-apparently-regulatory-intelligence-ma-slice-5-add-or-update-test-va: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 206,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/apparently"
      }
    ]
