PROJECT: illuminati

- id: chatgpt-local-reconcile-illuminati-f5da44e3ddc9
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
    `f5da44e3ddc912130e200cbb840946b7c984cf32417b16d281e35ef3016469f6`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "error": "git metadata no longer resolves",
        "kind": "broken_codex_git_worktree",
        "newest_mtime": 1784859305,
        "path": "/Users/kpasch/Documents/Codex/2026-07-22/impl/work/Trojun-incomplete-20260723"
      },
      {
        "kind": "codex_output_artifact",
        "mtime": 1786461567,
        "path": "/Users/kpasch/Documents/Codex/2026-07-22/fnd/outputs/illuminati-fixed.zip",
        "sha256": "007a783c58d58517a9d08b4e6fa9fab930cd4106c0e3603ce639b64863b6d1cb",
        "size": 2203525
      },
      {
        "branch": "master",
        "change_count": 3,
        "changes": [
          "PROMPT-ILLUMINATI-ABSORPTION.md",
          "PROMPT-SMARTER-CAPABILITY-BRIDGE.md",
          "cowork-backlog/backlog.json"
        ],
        "changes_digest": "b76768751980bffeb5c76d778b69efda490c6481857c809a0364a3522a0bceb4",
        "head": "8f0a56079815b8d47b87e92180da89fe0dce403b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786417887,
        "path": "/Users/kpasch/Documents/Trojun"
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
        "branches_digest": "8e731472cfd23b13dd3fa3e665f281d8306848c8352fe042d8b475c7d1581d47",
        "branches_sample": [
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
            "committed_at": 1786026386,
            "ref": "agent/dropbox-apparently-one-apparently-illuminati-unification-capability--escalation-",
            "sha": "6baa25d7f7abb599281f79ea15f5c74d52e9b8e0",
            "subject": "agent: dropbox-apparently-one-apparently-illuminati-unification-capability--escalation-"
          },
          {
            "committed_at": 1786024813,
            "ref": "agent/dropbox-beethoven-core-integrity-audit-merge-safety-self-protection--group-5",
            "sha": "0d6f299650d0564c98dbdc338a076a5c4526cdf6",
            "subject": "agent: dropbox-beethoven-core-integrity-audit-merge-safety-self-protection--group-5"
          },
          {
            "committed_at": 1785989364,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-s-slice-1",
            "sha": "0377c338f724e8469475bd80170689ada36f230d",
            "subject": "agent: federation 50-500X extensions (a-d), all four"
          },
          {
            "committed_at": 1785989364,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-s-slice-3",
            "sha": "0377c338f724e8469475bd80170689ada36f230d",
            "subject": "agent: federation 50-500X extensions (a-d), all four"
          },
          {
            "committed_at": 1785989364,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-s-slice-4",
            "sha": "0377c338f724e8469475bd80170689ada36f230d",
            "subject": "agent: federation 50-500X extensions (a-d), all four"
          },
          {
            "committed_at": 1786017963,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-s-slice-5",
            "sha": "360207b4b3e0549a24bcd880453c7577fb31f962",
            "subject": "agent: federated entity resolution \u2014 illuminati side of the identity spine"
          },
          {
            "committed_at": 1785970833,
            "ref": "agent/dropbox-cross-app-hivemind-federation-one-market-shaped-intelligence-50-500x-extensions-build-all",
            "sha": "395038582d3c3c846fb48ea47024180ea9e7f127",
            "subject": "agent: federation 50-500X extensions (a-d), all four"
          },
          {
            "committed_at": 1786022958,
            "ref": "agent/dropbox-foulkon-the-decision-instrument-full-implementation-group-1",
            "sha": "bfebb4bc9493f737eabd1ce1bb3eff41117dfa3e",
            "subject": "agent: dropbox-foulkon-the-decision-instrument-full-implementation-group-1"
          },
          {
            "committed_at": 1786025286,
            "ref": "agent/dropbox-foulkon-the-decision-instrument-full-implementation-group-3",
            "sha": "6fdf7204ebae5b625140d58e468f747686c22e1a",
            "subject": "agent: dropbox-foulkon-the-decision-instrument-full-implementation-group-3"
          },
          {
            "committed_at": 1786023933,
            "ref": "agent/dropbox-foulkon-the-decision-instrument-full-implementation-group-4",
            "sha": "1a07e1a9007e2a5fc8bfef2cd6b5c2b4ca83520e",
            "subject": "agent: dropbox-foulkon-the-decision-instrument-full-implementation-group-4"
          },
          {
            "committed_at": 1786023491,
            "ref": "agent/dropbox-operator-approved-full-improvements-document-build-in-full-2-contracts",
            "sha": "049321e9f3c2505b1b515e445df78b8fc23666e6",
            "subject": "agent: dropbox-operator-approved-full-improvements-document-build-in-full-2-contracts"
          },
          {
            "committed_at": 1786025698,
            "ref": "agent/dropbox-operator-approved-full-improvements-document-build-in-full-2-group-3",
            "sha": "d5cabfebee16ffacca59fcf8000336cd1e380fa6",
            "subject": "agent: dropbox-operator-approved-full-improvements-document-build-in-full-2-group-3"
          },
          {
            "committed_at": 1786025537,
            "ref": "agent/dropbox-operator-approved-full-improvements-document-build-in-full-2-group-4",
            "sha": "e80e6dc6c05b1151a0992dcdadabaaaf78eefeba",
            "subject": "agent: dropbox-operator-approved-full-improvements-document-build-in-full-2-group-4"
          },
          {
            "committed_at": 1786026534,
            "ref": "agent/dropbox-operator-approved-full-improvements-document-build-in-full-2-group-5",
            "sha": "cb5471d23e187a736718761d3a4b5eb096a57cef",
            "subject": "agent: coverage map + versioned-everything (group-5, illuminati side)"
          },
          {
            "committed_at": 1786025987,
            "ref": "agent/dropbox-precedent-graph-compression-corpus-wide-zero-token-reasoning-group-1-cit",
            "sha": "37f338b184f69e1c4f673b89e4459e86d23afa3b",
            "subject": "agent: dropbox-precedent-graph-compression-corpus-wide-zero-token-reasoning-group-1-cit"
          },
          {
            "committed_at": 1786138410,
            "ref": "agent/dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-1",
            "sha": "4f3122c824accf99b557b80f3efc4308abe72f28",
            "subject": "agent: dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-1"
          },
          {
            "committed_at": 1786025808,
            "ref": "agent/dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-4",
            "sha": "7155dce13c71121190e04dd8f8e5be990fa436b3",
            "subject": "agent: hedge 1-click submits an indication and opens consent, never a trade"
          },
          {
            "committed_at": 1786024460,
            "ref": "agent/dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-5",
            "sha": "a644c61de004fcbe9ec15381408a1c284662415c",
            "subject": "agent: dropbox-tomorrow-foulkon-hedge-bridge-transferspec-population-1-clic-group-5"
          },
          {
            "committed_at": 1786026865,
            "ref": "agent/dropbox-vigil-foulkon-enforcement-bridge-enforcementspec-population-group-4",
            "sha": "1893305f67fb542e0bdb52125ae124bac9356048",
            "subject": "agent: dropbox-vigil-foulkon-enforcement-bridge-enforcementspec-population-group-4"
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
            "committed_at": 1786026865,
            "ref": "orchestrator/dev",
            "sha": "1893305f67fb542e0bdb52125ae124bac9356048",
            "subject": "agent: dropbox-vigil-foulkon-enforcement-bridge-enforcementspec-population-group-4"
          },
          {
            "committed_at": 1785708675,
            "ref": "review/agent-access",
            "sha": "38ae4dd345d3a4a595cf09ec8002200ae862d4d1",
            "subject": "Merge branch 'agent/dropbox-beethoven-core-integrity-audit-merge-safety-self-protection--group-1' (auto-resolved)"
          }
        ],
        "branches_total": 31,
        "count": 31,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/illuminati"
      },
      {
        "count": 551,
        "items_digest": "adcd58a11dd97413a6b72f71bba740ecbcfc792b6f520233b35f207385332a3e",
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
            "created_at": 1785716109,
            "ref": "refs/orch-rescue/20260803T001509-illuminati-9be0d8cb",
            "sha": "9be0d8cb1cbec1b95190517c70a440788976dfef",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716512,
            "ref": "refs/orch-rescue/20260803T002153-dropbox-latency-hiding-decision-dag-gradient-displays-with-zero-appa-contracts-63ef240e",
            "sha": "63ef240e3e96cb79b305aa7046db15d8ed8f7400",
            "subject": "On agent/dropbox-latency-hiding-decision-dag-gradient-displays-with-zero-appa-contracts: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717289,
            "ref": "refs/orch-rescue/20260803T003449-illuminati-8d6ba532",
            "sha": "8d6ba5329eb1cdd82226741745dbc43de49b6933",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717568,
            "ref": "refs/orch-rescue/20260803T003928-illuminati-f1cf66ee",
            "sha": "f1cf66eef1b934ef467726a3d1acec70e9d90864",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
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
            "created_at": 1785718292,
            "ref": "refs/orch-rescue/20260803T005133-illuminati-2f49134c",
            "sha": "2f49134c5f22f3298955b9bc7aa6e33047cf4a37",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
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
            "created_at": 1785719016,
            "ref": "refs/orch-rescue/20260803T010336-illuminati-6f17db2c",
            "sha": "6f17db2c08e175d6880de3d51bd4815bd2818580",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785719351,
            "ref": "refs/orch-rescue/20260803T010911-illuminati-28040edd",
            "sha": "28040eddbbd29ded6c46961f32c4483bccad061a",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785719725,
            "ref": "refs/orch-rescue/20260803T011525-ext-streaming-terms-d98946c2",
            "sha": "d98946c286ee620ef4c4bace77ab326fb98c359d",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785720599,
            "ref": "refs/orch-rescue/20260803T013000-illuminati-99128a98",
            "sha": "99128a98d35bc5a61df4e9ea2fd1ad3b0253975d",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785721166,
            "ref": "refs/orch-rescue/20260803T013926-illuminati-b63678b3",
            "sha": "b63678b3a958d6902f51b6812c8c1b871b86f7d6",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785721509,
            "ref": "refs/orch-rescue/20260803T014509-oc-autoclear-policy-d1d17062",
            "sha": "d1d1706271c4298494a2b1a89c4dba73b587fedb",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785721939,
            "ref": "refs/orch-rescue/20260803T015219-illuminati-2e43e393",
            "sha": "2e43e3938103c44e86ce6afa9f21d8e814e58123",
            "subject": "On review/agent-access: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 551,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/illuminati"
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
