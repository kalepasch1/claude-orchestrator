PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-e101f01e0ee1
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
    `e101f01e0ee181831c8268222ea20f1c7964f93f19f01ccb416fb5d1e934959e`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 368,
        "items_digest": "17f7ad698a2ffe45d27dba92706bf3d5db9e4d8e045c07e419917f8a86761716",
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
            "created_at": 1785846886,
            "ref": "refs/orch-rescue/20260804T133253-apparently-f95dc3e8",
            "sha": "f95dc3e858d15a632954b303fb61dadd3d6bfc92",
            "subject": "fix(cron): drop javascript-opentimestamps in audit-attestation"
          },
          {
            "created_at": 1785850377,
            "ref": "refs/orch-rescue/20260804T134934-apparently-c1c33def",
            "sha": "c1c33defcd3fcf8010e5ff9d78216a0f4c41547e",
            "subject": "Merge branch 'agent/recover-missing-branch-backlog-batch-apparently-015d6d4-adapt-lint-code-adapt-slice-1-linting' (auto-resolved)"
          },
          {
            "created_at": 1785851623,
            "ref": "refs/orch-rescue/20260804T140506-apparently-36bbedde",
            "sha": "36bbedde053946abc43b99cd579f19ec959dc956",
            "subject": "Merge branch 'agent/relfix-apparently-07230328' (auto-resolved)"
          },
          {
            "created_at": 1785853174,
            "ref": "refs/orch-rescue/20260804T142139-apparently-37048bce",
            "sha": "37048bce1b726e130a8be059c6c4a3ffb2ac95c9",
            "subject": "feat(consilium/disclosure): shared contracts for Consilium audit + conspicuous-disclosure engine"
          },
          {
            "created_at": 1785854011,
            "ref": "refs/orch-rescue/20260804T143331-relfix-apparently-1213155610fa-c29feb1f",
            "sha": "c29feb1fe054a7022827150730d5304907417821",
            "subject": "On agent/relfix-apparently-1213155610fa: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785854626,
            "ref": "refs/orch-rescue/20260804T144346-dropbox-tomorrow-apparently-pareto-bridges-perpetual-spine-v1-unifie-contracts-680fc0f0",
            "sha": "680fc0f03511924cc10a38c4a15374b939e8e322",
            "subject": "On agent/dropbox-tomorrow-apparently-pareto-bridges-perpetual-spine-v1-unifie-contracts: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785856315,
            "ref": "refs/orch-rescue/20260804T151155-backlog-batch-apparently-0d157dd-recover-hive-entity-relationship-source-f9c1ea98",
            "sha": "f9c1ea989fc923dd5d59fb145cf4e1ffc647b69b",
            "subject": "On agent/backlog-batch-apparently-0d157dd-recover-hive-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785856532,
            "ref": "refs/orch-rescue/20260804T151802-apparently-daee07f1",
            "sha": "daee07f18f2f534c385c371b0aa3b657df6f36ce",
            "subject": "Merge branch 'agent/relfix-apparently-1213155610fa' (auto-resolved)"
          }
        ],
        "items_total": 368,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/apparently"
      }
    ]
