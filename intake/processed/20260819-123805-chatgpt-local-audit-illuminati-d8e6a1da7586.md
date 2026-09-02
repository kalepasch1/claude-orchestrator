PROJECT: illuminati

- id: chatgpt-local-reconcile-illuminati-d8e6a1da7586
  title: Reconcile local ChatGPT/Codex build evidence for illuminati
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
    `d8e6a1da7586082f29ee9c2c0f6b3d2ffc9c6b1fdb2096cda1116ddb2fece87f`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 709,
        "items_digest": "a4e9663218c56ecca6419fa6777dad3e6b0647179c796c940ab8778d8c6b05c4",
        "items_sample": [
          {
            "created_at": 1785715612,
            "ref": "refs/orch-rescue/20260803T000652-illuminati",
            "sha": "9863e3d286ad309d71031e0881823654d1539001",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-illuminati",
            "sha": "14c5a60b2b5116f23c5d05494dc2bfb118e56365",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715852,
            "ref": "refs/orch-rescue/20260803T001052-illuminati",
            "sha": "0743a1f8314e769fbfc8b23e1677591fbc7c6b10",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716512,
            "ref": "refs/orch-rescue/20260803T002153-dropbox-latency-hiding-decision-dag-gradient-displays-with-zero-appa-contracts-63ef240e",
            "sha": "63ef240e3e96cb79b305aa7046db15d8ed8f7400",
            "subject": "On agent/dropbox-latency-hiding-decision-dag-gradient-displays-with-zero-appa-contracts: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717841,
            "ref": "refs/orch-rescue/20260803T004401-breach-remediation-e9b16b5d",
            "sha": "e9b16b5d0cb40f73285b07b55447ee96c2bf8044",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717841,
            "ref": "refs/orch-rescue/20260803T004402-convention-conformance-lints-65b3782d",
            "sha": "65b3782d01a73380acd16fbc66461450fe22d9c5",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717842,
            "ref": "refs/orch-rescue/20260803T004402-economic-scheduler-revenue-80479e31",
            "sha": "80479e319ec7f85dbd5916374cc65b4737aa5215",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717843,
            "ref": "refs/orch-rescue/20260803T004403-merged-diff-memory-554d8c62",
            "sha": "554d8c628bf0bd5615c4689a8baa4c3886aaad1b",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717844,
            "ref": "refs/orch-rescue/20260803T004404-orch-config-consumption-4c531394",
            "sha": "4c53139441b307c6e9a37e541caf7860b4c1ab87",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717845,
            "ref": "refs/orch-rescue/20260803T004405-pinned-express-lane-e3d28fde",
            "sha": "e3d28fde1676122758b4b298c1a9b7a1408df390",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717846,
            "ref": "refs/orch-rescue/20260803T004406-prompt-evolution-bandit-2993f266",
            "sha": "2993f266cab90a4a8e83e976991e1187dc6c98fa",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718294,
            "ref": "refs/orch-rescue/20260803T005134-cade-mirror-negotiation-9fbc801c",
            "sha": "9fbc801cb4cdff30009194e845dbab8e0e8f1455",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718295,
            "ref": "refs/orch-rescue/20260803T005135-cc-legacy-margin-removal-48ecee51",
            "sha": "48ecee51bf22c22f071045d3aa3359fba8deb223",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718296,
            "ref": "refs/orch-rescue/20260803T005136-cc-mutual-default-fund-6bc4efcb",
            "sha": "6bc4efcb2653f8746d41ab00e5907ed379d2f039",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718296,
            "ref": "refs/orch-rescue/20260803T005136-cc-solvency-passport-3c13e4f3",
            "sha": "3c13e4f3ce458002b12cdf2cbb382159005936fc",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718297,
            "ref": "refs/orch-rescue/20260803T005137-hive-enforcement-velocity-index-73d12036",
            "sha": "73d12036a6ff61adcdb7c574746d98cf83b10017",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718297,
            "ref": "refs/orch-rescue/20260803T005138-hive-support-entity-relationship-source-63ca31d9",
            "sha": "63ca31d9ff09a470d404aa86189405714925f9c8",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718299,
            "ref": "refs/orch-rescue/20260803T005139-ploeh-s2s-bridge-tomorrow-2ecc6f33",
            "sha": "2ecc6f33c319f7d876eaa07c14f64d23b5d4780d",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718300,
            "ref": "refs/orch-rescue/20260803T005140-smarter-5-95-6f985290",
            "sha": "6f9852902171abb533318c324fef92c39685f522",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785719725,
            "ref": "refs/orch-rescue/20260803T011525-ext-streaming-terms-d98946c2",
            "sha": "d98946c286ee620ef4c4bace77ab326fb98c359d",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785721509,
            "ref": "refs/orch-rescue/20260803T014509-oc-autoclear-policy-d1d17062",
            "sha": "d1d1706271c4298494a2b1a89c4dba73b587fedb",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785723092,
            "ref": "refs/orch-rescue/20260803T021132-toolchain-repair-53402dab-slice-1-4aff6417",
            "sha": "4aff6417a195f37fff3749b81d40fe60465e417e",
            "subject": "On agent/toolchain-repair-53402dab-slice-1: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785802183,
            "ref": "refs/orch-rescue/20260804T000943-prompt-evolution-bandit-154e7c9c",
            "sha": "154e7c9c4993656dbdf61877ba294085cfcfaca5",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785802184,
            "ref": "refs/orch-rescue/20260804T000944-smarter-5-95-80dc0ab7",
            "sha": "80dc0ab779aa9cc40df02cc7b8a3a51968ca585c",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785805840,
            "ref": "refs/orch-rescue/20260804T011040-causal-outcome-feedback-d78050c3",
            "sha": "d78050c3a2c74a7a45a40bebc6362007ee94e090",
            "subject": "On agent/causal-outcome-feedback: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785805843,
            "ref": "refs/orch-rescue/20260804T011043-hive-arbitrage-enforcement-hook-db789f2f",
            "sha": "db789f2fb60e0ab5da42ab692e0e0aa445c97879",
            "subject": "On agent/hive-arbitrage-enforcement-hook: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785862923,
            "ref": "refs/orch-rescue/20260804T170203-ensemble-on-hard-72e1d6b9",
            "sha": "72e1d6b9817168bcf1fbc86889ea45323cc74b72",
            "subject": "On agent/ensemble-on-hard: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785862924,
            "ref": "refs/orch-rescue/20260804T170204-orch-cross-project-depends-ec7d2915",
            "sha": "ec7d29156fc7e842b103e83e57507902dbd55217",
            "subject": "On agent/orch-cross-project-depends: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785891337,
            "ref": "refs/orch-rescue/20260805T005538-illuminati-b1e68774",
            "sha": "b1e687748a73d2ec053290168678983436d8a856",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785891802,
            "ref": "refs/orch-rescue/20260805T010323-illuminati-27b48948",
            "sha": "27b48948f4eeebbc49a69a90d99ba330536c6dc1",
            "subject": "On master: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 709,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/illuminati"
      },
      {
        "branch": "agent/v15-fractal-runtime",
        "change_count": 228,
        "changes_digest": "340790104fe8ccc13aa489dddff0f4a974d30029236d58cbdf1d3f9ccac07ed8",
        "changes_sample": [
          "runner/deploy_batcher.py",
          "runner/qa_agents.py",
          "runner/suggestion_engine.py",
          "runner/verification_pipeline.py",
          "web/components/CadeScore.vue",
          "web/components/CascadeConfidenceViz.vue",
          "web/components/CostRoutingPanel.vue",
          "web/components/FleetTopologyMap.vue",
          "web/components/IlluminatiLogo.vue",
          "web/components/QAResultsPanel.vue",
          "web/components/SpeculativeRaceViz.vue",
          "web/components/StatusPill.vue",
          "web/components/SuggestionPanel.vue",
          "web/components/SystemStatusBar.vue",
          "web/components/TerminalInput.vue",
          "web/components/TerminalStreamOutput.vue",
          "web/components/VerificationChecklist.vue",
          "web/composables/useCascadeStream.ts",
          "web/composables/useFleetWebSocket.ts",
          "web/composables/useOrchestratorSnapshot.ts",
          "web/composables/useRealtimeTable.ts",
          "web/pages/account.vue",
          "web/pages/advisory.vue",
          "web/pages/agents.vue",
          "web/pages/alternatives.vue",
          "web/pages/assessments.vue",
          "web/pages/changes.vue",
          "web/pages/create-account.vue",
          "web/pages/dashboard.vue",
          "web/pages/dashboard/compliance.vue"
        ],
        "changes_total": 100,
        "head": "e3b5c172f8eca44486b43e74b203abc2f4719d91",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1785072229,
        "path": "/Users/kpasch/Documents/_Trojun_archived"
      },
      {
        "branches": [
          {
            "committed_at": 1786076753,
            "ref": "agent/backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-lint-and-typecheck-fix-lint-and",
            "sha": "b1e009544bfa1b6c47096bdc47094272654174d3",
            "subject": "regen-from-cache(template): backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-lint-and-typecheck-fix-lint-and"
          },
          {
            "committed_at": 1785963949,
            "ref": "agent/backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-typechec",
            "sha": "8de7c7ba8891f83dcc5748c2e547152e9a475d7c",
            "subject": "recovery-intent-stub: recover-missing-branch-backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-typechec"
          },
          {
            "committed_at": 1784951522,
            "ref": "agent/backlog-batch-illuminati-dd47b58",
            "sha": "80351380fe5b6765a9aab1b2d680dde2049c362b",
            "subject": "agent: backlog-batch-illuminati-dd47b58"
          },
          {
            "committed_at": 1785895886,
            "ref": "agent/backlog-batch-illuminati-dd47b58-apply-patch-template",
            "sha": "72161a82ebfac9ef205579fec550813e1c94b9d2",
            "subject": "regen-from-cache(template): backlog-batch-illuminati-dd47b58-apply-patch-template"
          },
          {
            "committed_at": 1785897647,
            "ref": "agent/backlog-batch-illuminati-dd47b58-patch-template",
            "sha": "41e82f8ad412caf59a04fac1a68d189d8aceb5d7",
            "subject": "regen-from-cache(template): backlog-batch-illuminati-dd47b58-patch-template"
          },
          {
            "committed_at": 1785944835,
            "ref": "agent/backlog-batch-illuminati-dd47b58-remove-duplicate-pricinggridreconstructi",
            "sha": "e00a315c78d50671014481931bc5e36e05e3e01f",
            "subject": "regen-from-cache(template): backlog-batch-illuminati-dd47b58-remove-duplicate-pricinggridreconstructi"
          },
          {
            "committed_at": 1786121882,
            "ref": "agent/divergent-illuminati-union-merge-symbol-loss-exitsemantic",
            "sha": "4dec422a18aad6ddf865488407f9d25be37ab80f",
            "subject": "regen-from-cache(template): divergent-illuminati-union-merge-symbol-loss-exitsemantic"
          },
          {
            "committed_at": 1785970833,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-shaped-intelligence-50-500x-extensions-build-all",
            "sha": "395038582d3c3c846fb48ea47024180ea9e7f127",
            "subject": "agent: federation 50-500X extensions (a-d), all four"
          },
          {
            "committed_at": 1787042193,
            "ref": "agent/dropbox-illuminati-production-closeout-20260812",
            "sha": "42c24fa79c0912c04fdfdd7c5ea491692440422d",
            "subject": "agent: dropbox-illuminati-production-closeout-20260812"
          },
          {
            "committed_at": 1786138410,
            "ref": "agent/dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-1",
            "sha": "4f3122c824accf99b557b80f3efc4308abe72f28",
            "subject": "agent: dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-1"
          },
          {
            "committed_at": 1785963949,
            "ref": "agent/recover-missing-branch-backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-typechec",
            "sha": "8de7c7ba8891f83dcc5748c2e547152e9a475d7c",
            "subject": "recovery-intent-stub: recover-missing-branch-backlog-batch-illuminati-d3ba8c6-weekly-lint-fix-typechec"
          },
          {
            "committed_at": 1785182261,
            "ref": "chatgpt/post-hardening-selftest-07271457",
            "sha": "13f7b62bb4531015f9641dce1e1eaa856278ffbe",
            "subject": "chore: post-hardening bridge selftest"
          },
          {
            "committed_at": 1785708675,
            "ref": "review/agent-access",
            "sha": "38ae4dd345d3a4a595cf09ec8002200ae862d4d1",
            "subject": "Merge branch 'agent/dropbox-beethoven-core-integrity-audit-merge-safety-self-protection--group-1' (auto-resolved)"
          },
          {
            "committed_at": 1785981360,
            "ref": "salvage/dirty-20260806-0158",
            "sha": "7cb6e50ad45678287780c925df1714fe4b3baae1",
            "subject": "salvage: in-flight tracked edits blocking auto_conflict_resolver (package-lock.json, verdict-cards.json)"
          }
        ],
        "count": 14,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/illuminati"
      },
      {
        "count": 9,
        "items": [
          {
            "created_at": 1786617218,
            "ref": "refs/orch-rescue/20260813T103338-Trojun-7281d4c3",
            "sha": "7281d4c3466938285fbedfdcea218fa77ff23271",
            "subject": "On codex/trojun-canonical-rename: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786796491,
            "ref": "refs/orch-rescue/20260815T122131-cade-mirror-negotiation-45ce0983",
            "sha": "45ce09830c9b9334c8a367e517a440743b903484",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786833667,
            "ref": "refs/orch-rescue/20260815T224107-Trojun-376c7479",
            "sha": "376c7479562d3354c93d3a8361583f4f09737be4",
            "subject": "On codex/trojun-canonical-rename: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786943438,
            "ref": "refs/orch-rescue/20260817T051038-rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544-510fe323",
            "sha": "510fe3239fafab00b171ee48802001ec04119f0b",
            "subject": "On agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786955278,
            "ref": "refs/orch-rescue/20260817T082758-relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch-658e087a",
            "sha": "658e087a7509ae2097b21c399cc81299a327c5d0",
            "subject": "On agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786955279,
            "ref": "refs/orch-rescue/20260817T082759-rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db-e8507caa",
            "sha": "e8507caadfd6b79bbdafdb324ee1b5dc1ba925c4",
            "subject": "On agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786491670,
            "ref": "refs/orch-rescue/20260817T083337-Trojun-b4769b8e",
            "sha": "b4769b8eeb5e7be26d84f5de011b1baa08ddb2ae",
            "subject": "Rename Illuminati application to Trojun"
          },
          {
            "created_at": 1786956357,
            "ref": "refs/orch-rescue/20260817T084557-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi-a2a99a1c",
            "sha": "a2a99a1c6b72804e17e406b7cec8e0a3b096a628",
            "subject": "On agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1786967844,
            "ref": "refs/orch-rescue/20260817T115724-orch-config-consumption-7e390167",
            "sha": "7e39016709009259045a8178cc583eb4b493e326",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          }
        ],
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/Trojun"
      },
      {
        "count": 1,
        "items": [
          {
            "created_at": 1784926508,
            "ref": "stash@{0}",
            "sha": "59d3965d38da47b06d4c1a20b48577aa5e0ecfb3",
            "subject": "WIP on master: 9725fd1 Optimize landing, auth, and dashboard pages for business model"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/illuminati"
      },
      {
        "branches": [
          {
            "committed_at": 1786491670,
            "ref": "codex/trojun-canonical-rename",
            "sha": "b4769b8eeb5e7be26d84f5de011b1baa08ddb2ae",
            "subject": "Rename Illuminati application to Trojun"
          }
        ],
        "count": 1,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/Trojun"
      },
      {
        "branches": [
          {
            "committed_at": 1785182261,
            "ref": "chatgpt/post-hardening-selftest-07271457",
            "sha": "13f7b62bb4531015f9641dce1e1eaa856278ffbe",
            "subject": "chore: post-hardening bridge selftest"
          }
        ],
        "count": 1,
        "kind": "unmerged_chatgpt_codex_branches",
        "repo": "/Users/kpasch/Documents/illuminati"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/Trojun",
        "routing": "illuminati"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/_Trojun_archived",
        "routing": "illuminati"
      }
    ]
