PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-d10e15217b00
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
    `d10e15217b00c6a188965d84e95ef7593dfa0e1ccf6a64163b3bab410f9b3fb2`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 359,
        "items_digest": "f351c01f02a55d5bf1d71ec5ba459b675c43b49cc93a5e15efa0c4cbb016acc2",
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
            "created_at": 1785860887,
            "ref": "refs/orch-rescue/20260804T162807-cc-legacy-margin-removal-1a4d5260",
            "sha": "1a4d526080fa1b69afb398901584f2e81561d377",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785867562,
            "ref": "refs/orch-rescue/20260804T181922-ext-streaming-terms-bb95091f",
            "sha": "bb95091f5d164f7d23c88a5d1b3022006409ba6c",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785705421,
            "ref": "refs/orch-rescue/20260804T185435-apparently-a439f783",
            "sha": "a439f7835e884662aa64e094f50acdc87d54d99b",
            "subject": "Merge branch 'agent/ploeh-s2s-bridge-tomorrow' into agent/cc-solvency-passport"
          },
          {
            "created_at": 1785907172,
            "ref": "refs/orch-rescue/20260805T051932-prompt-evolution-bandit-30bcf532",
            "sha": "30bcf53289e74eef0e941dae18a279a7a6a60577",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785907172,
            "ref": "refs/orch-rescue/20260805T051932-smarter-5-95-3f14cfb2",
            "sha": "3f14cfb2a164a197f963a861b1c7d26184c6fdfd",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785920644,
            "ref": "refs/orch-rescue/20260805T090404-ensemble-on-hard-ac05483b",
            "sha": "ac05483b013827456fdab3283331567b7db39a1d",
            "subject": "On agent/ensemble-on-hard: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785920645,
            "ref": "refs/orch-rescue/20260805T090405-ext-streaming-terms-62182d5e",
            "sha": "62182d5ec528cb594fd7971486f7b4460a27ffa7",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785920646,
            "ref": "refs/orch-rescue/20260805T090406-hive-arbitrage-enforcement-hook-eafee8c2",
            "sha": "eafee8c24bae5a4504931c9ed9fbc4854a77cd1b",
            "subject": "On agent/hive-arbitrage-enforcement-hook: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 359,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/apparently"
      },
      {
        "bridge_result_tail": "[chatgpt-bridge] repo=apparently root=/Users/kpasch/Documents/apparently branch=chatgpt/absorb-otc-payoff-slice1-20260817-08171922\n[chatgpt-bridge] default branch: master\nApplying: absorb(otc): payoff DSL + composite payoff compiler from Illuminati\n[chatgpt-bridge] committed \u2014 4 file(s) changed\nremote: \nremote: Create a pull request for 'chatgpt/absorb-otc-payoff-slice1-20260817-08171922' on GitHub by visiting:        \nremote:      https://github.com/kalepasch1/apparently/pull/new/chatgpt/absorb-otc-payoff-slice1-20260817-08171922        \nremote: \nremote: GitHub found 85 vulnerabilities on kalepasch1/apparently's default branch (7 critical, 43 high, 26 moderate, 9 low). To find out more, visit:        \nremote:      https://github.com/kalepasch1/apparently/security/dependabot        \nremote: \n[chatgpt-bridge] pushed branch chatgpt/absorb-otc-payoff-slice1-20260817-08171922\n[chatgpt-bridge] PR: https://github.com/kalepasch1/apparently/pull/44\nOK: apparently \u2014 https://github.com/kalepasch1/apparently/pull/44\n",
        "kind": "chatgpt_bridge_artifact",
        "mtime": 1787008943,
        "path": "/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260817-192242--apparently--absorb-otc-payoff-slice1-20260817.patch",
        "sha256": "0d42e139cd99b242400bb08f5721b23f897539fa06eafa55f4d8265acd71ee88",
        "size": 70639,
        "status": "applied"
      },
      {
        "bridge_result_tail": "[chatgpt-bridge] repo=apparently root=/Users/kpasch/Documents/apparently branch=chatgpt/absorb-otc-payoff-slice1-v2-20260818-08172017\n[chatgpt-bridge] default branch: master\nApplying: absorb(otc): payoff DSL + composite payoff compiler from Illuminati\nApplying: fix(otc): the confidence gate could not fail, so make it able to\n[chatgpt-bridge] committed \u2014 4 file(s) changed\nremote: \nremote: Create a pull request for 'chatgpt/absorb-otc-payoff-slice1-v2-20260818-08172017' on GitHub by visiting:        \nremote:      https://github.com/kalepasch1/apparently/pull/new/chatgpt/absorb-otc-payoff-slice1-v2-20260818-08172017        \nremote: \nremote: GitHub found 85 vulnerabilities on kalepasch1/apparently's default branch (7 critical, 43 high, 26 moderate, 9 low). To find out more, visit:        \nremote:      https://github.com/kalepasch1/apparently/security/dependabot        \nremote: \n[chatgpt-bridge] pushed branch chatgpt/absorb-otc-payoff-slice1-v2-20260818-08172017\n[chatgpt-bridge] PR: https://github.com/kalepasch1/apparently/pull/48\nOK: apparently \u2014 https://github.com/kalepasch1/apparently/pull/48\n",
        "kind": "chatgpt_bridge_artifact",
        "mtime": 1787012045,
        "path": "/Users/kpasch/Documents/chatgpt-dropbox/_applied/20260817-201758--apparently--absorb-otc-payoff-slice1-v2-20260818.patch",
        "sha256": "e1f71dc951cbaf9cd8bdb40250c64c74c89ac3ab731c93519a368034c005ec0e",
        "size": 87180,
        "status": "applied"
      },
      {
        "branch": "DETACHED",
        "change_count": 5,
        "changes": [
          "scripts/check-rls.mjs",
          "scripts/lib/rls-audit-core.mjs",
          "server/api/foulkon/optimal-conclusion.post.ts",
          "tests/api/foulkon-optimal-conclusion.test.ts",
          "tests/rls-audit-core.test.ts"
        ],
        "changes_digest": "b09b8622948e10ff864e1c671196c44e4cb1fe60dbede9cc28fce8220aa57684",
        "head": "f905abb3a649b53705f18cdb9b502ef26ea4cc51",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786573957,
        "path": "/Users/kpasch/Documents/apparently-wt/shadow-sandbox-20260812"
      },
      {
        "branch": "worktree-agent-a4c6063da00ab1e59",
        "change_count": 4,
        "changes": [
          "server/engines/pattern-detector.ts",
          "server/engines/promo-ai-refiner.ts",
          "server/engines/promo-bot-calibration.ts",
          "server/routes/submission-autopilot.ts"
        ],
        "changes_digest": "951589030cc99a0563953dce997dbed96d6484a9199fb0e6c3d4515784741cd0",
        "head": "10dbd519ae402ded95cb26cdf4fb2f080cc3fce0",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786968586,
        "path": "/Users/kpasch/Documents/apparently/.claude/worktrees/agent-a4c6063da00ab1e59"
      },
      {
        "branch": "DETACHED",
        "change_count": 17,
        "changes": [
          "app/lib/coverage/contracts.ts",
          "app/lib/coverage/matrix-engine.test.ts",
          "app/lib/coverage/matrix-engine.ts",
          "app/pages/coverage/[org].vue",
          "app/pages/embed/coverage/[org].vue",
          "lib/coverage/contracts.ts",
          "lib/coverage/fixtures.ts",
          "lib/coverage/qa-runner.ts",
          "lib/coverage/registry.ts",
          "server/api/coverage/picture.get.ts",
          "server/api/public/coverage/[org]/attest.get.ts",
          "server/api/public/coverage/[org]/attestation.jsonld.get.ts",
          "server/api/public/coverage/__tests__/jsonld.test.ts",
          "server/api/public/coverage/verify.get.ts",
          "tests/coverage/contracts.test.ts",
          "tests/coverage/qa-runner.test.ts",
          "tests/coverage/registry.test.ts"
        ],
        "changes_digest": "f02db0e93ad470e80f9fb95ae19f98bc58c61defd26f4d287c20705d54b4dc34",
        "head": "33f92ed25b7e875d23d4da1f24ebc3c391328129",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/a8a63f0482aed16feeac"
      },
      {
        "branches": [
          {
            "committed_at": 1785990738,
            "ref": "agent/backlog-batch-apparently-0ef7cd6-kpi-dashboard-recovery-implement-kpi-logic",
            "sha": "2d01e4879857ad42d1053c1f7718e43011541acc",
            "subject": "feat: integrate KPI metrics data layer into dashboard"
          },
          {
            "committed_at": 1785981089,
            "ref": "agent/hive-arbitrage-enforcement-hook",
            "sha": "5e6cc092f81598ef46ccf1d60e80dfc045637664",
            "subject": "agent: hive arbitrage enforcement hook \u2014 commit it, test it, fix the two bugs the tests found"
          },
          {
            "committed_at": 1786422029,
            "ref": "agent/illuminati-absorption-contracts",
            "sha": "2644606363fe093ca01baea7ddad02f4c9849d20",
            "subject": "agent: illuminati-absorption-contracts"
          },
          {
            "committed_at": 1786536013,
            "ref": "agent/reconcile-conflicts-72b7b924-be189d2d-focused-followup",
            "sha": "96f3e42f9d7b56a451d4f333ecd9da93d31c7360",
            "subject": "agent: reconcile-conflicts-72b7b924-be189d2d-focused-followup"
          },
          {
            "committed_at": 1787041109,
            "ref": "agent/v2-plan-intelligence-rail-and-renames",
            "sha": "a72ac81d68ecd567b94b5348cd1ec51b8aadb921",
            "subject": "agent: v2-plan-intelligence-rail-and-renames"
          },
          {
            "committed_at": 1785360970,
            "ref": "review/agent-access",
            "sha": "ef3370b6ef890031497f6ee936ee0c9a11cc2996",
            "subject": "test(hive): add shared-artifact-writes test suite"
          }
        ],
        "count": 6,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/apparently"
      },
      {
        "count": 33,
        "items_digest": "300ffe4175067ed75335ddfff9a5462c238666857d4afdd8c6b59384e8a5ebaa",
        "items_sample": [
          {
            "created_at": 1787005584,
            "ref": "stash@{0}",
            "sha": "154f37f6fdec44148e56e2bfac4502deb290d2a2",
            "subject": "On agent/smarter-5-95: stray settings.json allowlist entries from smarter-5-95 session"
          },
          {
            "created_at": 1786923186,
            "ref": "stash@{1}",
            "sha": "a47eb3de83295f0c0598f51b62add5cf66f805fa",
            "subject": "WIP on landing-revamp-20260811: c36c567a fix(landing): preserve intelligence and license surfaces"
          },
          {
            "created_at": 1786584219,
            "ref": "stash@{2}",
            "sha": "a5d92776e792c5726d337eb1bb9fb78277ce500e",
            "subject": "On landing-revamp-20260811: landing-index-rewrite-639line-FAILS-GUARD-SUITES-20260813"
          },
          {
            "created_at": 1786566169,
            "ref": "stash@{3}",
            "sha": "5493e44fbd4ffda6825a5f1224d4e769b0655adf",
            "subject": "On orchestrator/dev: shadow-round2 draft: tribal namespace reconciliation (unverified, preserved)"
          },
          {
            "created_at": 1785935220,
            "ref": "stash@{4}",
            "sha": "5e4c1bee9da5a2a3ee4ea503efd7e8145b7f7cfc",
            "subject": "On agent/cc-solvency-passport: wip-agent-branch-1785935220"
          },
          {
            "created_at": 1785676921,
            "ref": "stash@{5}",
            "sha": "0ce89f31c993c4c473fc64934c03f561c00eceac",
            "subject": "WIP on master: 2dd3a3e0 Merge branch 'agent/backlog-batch-apparently-0ef7cd6-kpi-dashboard-recovery-analyze-and-select-diff-' (auto-resolved)"
          },
          {
            "created_at": 1785587051,
            "ref": "stash@{6}",
            "sha": "e891267ee37bcdea5cd62307d91227ca37c64335",
            "subject": "WIP on master: eee30c74 merge: Stripe webhook middleware exemptions (payments launch fix)"
          },
          {
            "created_at": 1785553645,
            "ref": "stash@{7}",
            "sha": "a3a3a55fe126775b2715f58123fab2a2459d89d3",
            "subject": "WIP on master: eee30c74 merge: Stripe webhook middleware exemptions (payments launch fix)"
          },
          {
            "created_at": 1785512030,
            "ref": "stash@{8}",
            "sha": "09785230d086c507155f1292f5832a3df343a25a",
            "subject": "On agent/hive-support-entity-relationship-source: agent-wip-guard"
          },
          {
            "created_at": 1785510761,
            "ref": "stash@{9}",
            "sha": "b2a65205cb8a4b006c41533ed25ef5abe80d9f4d",
            "subject": "WIP on agent/act-e2e-usable-smoke: e8e4d34f fix(e2e-hive-usable): remove networkidle waits and simplify async patterns to prevent timeout"
          },
          {
            "created_at": 1785468869,
            "ref": "stash@{10}",
            "sha": "04d74d7f992279e4912a136e6a610b1300407ac2",
            "subject": "WIP on agent/hive-support-entity-relationship-source: 39101f3e fix(hive): correct entity-relationship-source test for missing orgLabel scenario"
          },
          {
            "created_at": 1785368694,
            "ref": "stash@{11}",
            "sha": "890df2fb6a7cebb7dd5d9a25f1b2b3e5812e9841",
            "subject": "WIP on agent/hive-support-entity-relationship-source: ca99b50c feat(hive): add entity-relationship-source fetcher and support-entity orchestration"
          },
          {
            "created_at": 1784991314,
            "ref": "stash@{12}",
            "sha": "ac18c82dc0f72ee40299ca083cbcd6c8be1223aa",
            "subject": "WIP on agent/cade-tribunal-counterparty-validate-batch-release--slice-2: 0b78d1db Merge branch 'master' of https://github.com/kalepasch1/apparently"
          },
          {
            "created_at": 1784755574,
            "ref": "stash@{13}",
            "sha": "806f4197fb5f286d7b6ec8b9b2fc21abc4f6c0b8",
            "subject": "On master: auto-stash before merge"
          },
          {
            "created_at": 1784686643,
            "ref": "stash@{14}",
            "sha": "9cdde87ad6352e20333c8b5ce6e6263d9017084a",
            "subject": "WIP on master: 8c26ce22 Merge branch 'worktree-agent-a8881439b52c6ca1d'"
          },
          {
            "created_at": 1784684715,
            "ref": "stash@{15}",
            "sha": "edd1a0734a4ed319e0b9e446f7026292fef1bdfb",
            "subject": "On master: pre-force-merge"
          },
          {
            "created_at": 1784565776,
            "ref": "stash@{16}",
            "sha": "0b7472d65e7ecdb6a985d76884dd1116d89e4270",
            "subject": "WIP on master: 9e7c4ad chore: commit uncommitted production changes"
          },
          {
            "created_at": 1784426674,
            "ref": "stash@{17}",
            "sha": "6039f593c4701ff807f3d2d37a922e8fe8d50a42",
            "subject": "WIP on agent/recover-missing-branch-corpus-metered-api-slice-2: da7fb11 feat: add metered corpus GET endpoint with usage tracking and rate limiting"
          },
          {
            "created_at": 1784416778,
            "ref": "stash@{18}",
            "sha": "1ef4684aae0ec80d020b738d50ebd0d25c5b4804",
            "subject": "WIP on master: a2d506f CADE expert mesh: 613K virtual experts, daily evolution cron, research tools, Ollama adapter"
          },
          {
            "created_at": 1784207993,
            "ref": "stash@{19}",
            "sha": "67138a2364e2940597262cdc45a63b529d42f11f",
            "subject": "WIP on agent/hive-ops-dashboards-exposures-and-regulatory-debt-panels: 7866c0a train: agent/pii-encryption-and-portal-rls-slice-1"
          },
          {
            "created_at": 1784192062,
            "ref": "stash@{20}",
            "sha": "0ccff4ac4fa94d8581a886ab54361f969bbe1d00",
            "subject": "WIP on master: a2d506f CADE expert mesh: 613K virtual experts, daily evolution cron, research tools, Ollama adapter"
          },
          {
            "created_at": 1784184024,
            "ref": "stash@{21}",
            "sha": "6a5f146d6e018c881663b8d02b8ee5e3e2938c1e",
            "subject": "WIP on agent/ploeh-s2s-bridge-apparently: 99474a9 feat: PLOEH S2S bridge with HMAC-SHA256 signing"
          },
          {
            "created_at": 1784181393,
            "ref": "stash@{22}",
            "sha": "e71961458a2ac1cbe305fbbc37c13fc11700e493",
            "subject": "WIP on master: e02c589 feat: add regulator cooperation handoff"
          },
          {
            "created_at": 1784176640,
            "ref": "stash@{23}",
            "sha": "8f7620851760e8d00106a3d96ed15ceaecf07183",
            "subject": "WIP on agent/rework-secret-rework-secret-license-passport-ad7131a-fb5b135: 82d431d docs: backlog batch consolidation 5bb26b4"
          },
          {
            "created_at": 1784176000,
            "ref": "stash@{24}",
            "sha": "d879de782eda04a758d10a49ebcd6a833ba95762",
            "subject": "WIP on recovery/concurrent-primary-20260715-apparently: cd565ab feat: schedule autonomous License OS factory"
          },
          {
            "created_at": 1784149374,
            "ref": "stash@{25}",
            "sha": "a66858a2810a08ca0f481b35afbc2614368faa5e",
            "subject": "WIP on agent/backlog-batch-apparently-e5d4a9c: c24ffce docs: backlog batch consolidation e5d4a9c"
          },
          {
            "created_at": 1784047102,
            "ref": "stash@{26}",
            "sha": "a7fbebaeef6fdcb90a5f4cd19c5b6152b007c102",
            "subject": "WIP on agent/rework-secret-rework-secret-license-passport-ad7131a-fb5b135: c2778e1 feat(license-passport): add informational license passport with public verify"
          },
          {
            "created_at": 1784042979,
            "ref": "stash@{27}",
            "sha": "5d1536dcab08ade67285216a26d3021493778540",
            "subject": "WIP on master: ed0dc42 agent/bx1: cade-decider-twin, cade-voi-intake-ui"
          },
          {
            "created_at": 1784003210,
            "ref": "stash@{28}",
            "sha": "b03a64a9fc755aa3211ea1ca09b4a5169fe784cd",
            "subject": "WIP on agent/position-outcome-endpoint-split-the-build-task-int-slice-1: 93d8c50 fix: correct supabase-typed import path (supabase-client does not exist) \u2014 unblocks nitro build"
          },
          {
            "created_at": 1783986858,
            "ref": "stash@{29}",
            "sha": "4f3daebd794cfb092cca14bbc261dac2a0584754",
            "subject": "WIP on agent/qafix-apparently-07130648: cf3aa40 agent/cade-league-eval-set-slice-2: add adversary-league-eval.test.ts pinning league routing determinism"
          }
        ],
        "items_total": 33,
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/apparently"
      },
      {
        "branches": [
          {
            "committed_at": 1787009026,
            "ref": "chatgpt/absorb-otc-payoff-slice1-20260817-08171922",
            "sha": "a1b096c970964201419cb4ee46ec4910971f2c3b",
            "subject": "absorb(otc): payoff DSL + composite payoff compiler from Illuminati"
          },
          {
            "committed_at": 1787012382,
            "ref": "chatgpt/absorb-otc-payoff-slice1-v2-20260818-08172017",
            "sha": "1d0491884455ae9c63ae6be680b99655a6b38b48",
            "subject": "fix(otc): the confidence gate could not fail, so make it able to"
          }
        ],
        "count": 2,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/apparently"
      }
    ]
