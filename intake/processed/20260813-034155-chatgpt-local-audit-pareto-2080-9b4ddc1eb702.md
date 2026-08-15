PROJECT: pareto-2080

- id: chatgpt-local-reconcile-pareto-2080-9b4ddc1eb702
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
    `9b4ddc1eb7027a968a402a95d357ec1125f2e9a3a4fb773f696249bffde54aa5`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786157244,
            "ref": "agent/backlog-batch-pareto-2080-5643cef-add-tax-velocity-section",
            "sha": "1dce4281ffd31588cd9e9828fd2e32e21ce759e1",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-5643cef-add-tax-velocity-section"
          },
          {
            "committed_at": 1786160723,
            "ref": "agent/backlog-batch-pareto-2080-5643cef-analyze-prior-merged-patterns",
            "sha": "04373ead9821deff81013376821149e7e6eeb606",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-5643cef-analyze-prior-merged-patterns"
          },
          {
            "committed_at": 1786155917,
            "ref": "agent/backlog-batch-pareto-2080-5643cef-buildfail-patch-template",
            "sha": "496b740c20fbf9c371ebbb2554d4232b2b7f89ed",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-5643cef-buildfail-patch-template"
          },
          {
            "committed_at": 1786157752,
            "ref": "agent/backlog-batch-pareto-2080-5643cef-identify-existing-owner-module",
            "sha": "cc320db8c6c948d35717fec7578ddcc2fed7978b",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-5643cef-identify-existing-owner-module"
          },
          {
            "committed_at": 1786163807,
            "ref": "agent/backlog-batch-pareto-2080-5643cef-integrate-agentic-coder-configuration",
            "sha": "22a8f412b95c580a635ad1a590c399046f000ab6",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-5643cef-integrate-agentic-coder-configuration"
          },
          {
            "committed_at": 1786202487,
            "ref": "agent/backlog-batch-pareto-2080-5643cef-setup-orchestration-pipeline-contract",
            "sha": "b7b9afe324baef5cb634da35a5cef8be4c63078b",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-5643cef-setup-orchestration-pipeline-contract"
          },
          {
            "committed_at": 1786167889,
            "ref": "agent/backlog-batch-pareto-2080-5643cef-stale-backlog-manifest-recovery",
            "sha": "cbd489cbf73955eb0e4681e0a1ca76b70cd15a98",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-5643cef-stale-backlog-manifest-recovery"
          },
          {
            "committed_at": 1786164549,
            "ref": "agent/backlog-batch-pareto-2080-a19cca3-apply-agentledger-esm-cjs-guard",
            "sha": "36c0c2e214eb03827a25dd5863589e37df1d337b",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-a19cca3-apply-agentledger-esm-cjs-guard"
          },
          {
            "committed_at": 1786164317,
            "ref": "agent/backlog-batch-pareto-2080-a19cca3-remove-duplicate-pricing-grid-reconstruc",
            "sha": "9485a00ba04c3e412bfe4e59fa18ed81045b27cc",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-a19cca3-remove-duplicate-pricing-grid-reconstruc"
          },
          {
            "committed_at": 1786188734,
            "ref": "agent/backlog-batch-pareto-2080-f133ba9",
            "sha": "1ac69cb14833bb958d23fbdd13faf94808244f0a",
            "subject": "recovery-intent-stub: backlog-batch-pareto-2080-f133ba9"
          },
          {
            "committed_at": 1786148762,
            "ref": "agent/canary-pareto-2080-20260722-reclaim-stale-running-canaries",
            "sha": "bd820616c997686355d811207ea8cae0d0e34143",
            "subject": "recovery-intent-stub: canary-pareto-2080-20260722-reclaim-stale-running-canaries"
          },
          {
            "committed_at": 1786149855,
            "ref": "agent/fix-remaining-engine-tests-fix-charitable-bunching-and-asset-locati-correct-asse",
            "sha": "baa6aac58aa9501be59e55ec2c7fba2ae41ed248",
            "subject": "recovery-intent-stub: fix-remaining-engine-tests-fix-charitable-bunching-and-asset-locati-correct-asse"
          },
          {
            "committed_at": 1786143782,
            "ref": "agent/fix-remaining-engine-tests-fix-charitable-bunching-and-asset-locati-correct-char",
            "sha": "1b0ad0bc918d7d21cd055bd3136903b8a9397487",
            "subject": "recovery-intent-stub: fix-remaining-engine-tests-fix-charitable-bunching-and-asset-locati-correct-char"
          },
          {
            "committed_at": 1786155292,
            "ref": "agent/fix-remaining-engine-tests-fix-money-velocity-and-mega-backdoor-rot-adapt-existi",
            "sha": "17af8b56d50adc82a03f1b5e6cf0b53bec0d2b68",
            "subject": "recovery-intent-stub: fix-remaining-engine-tests-fix-money-velocity-and-mega-backdoor-rot-adapt-existi"
          },
          {
            "committed_at": 1786150779,
            "ref": "agent/gate-esm-cjs-guard-document-esm-only-policy-add-esm-only-statement",
            "sha": "e311b4682a1af73120dfea094ec6976150cf2981",
            "subject": "recovery-intent-stub: gate-esm-cjs-guard-document-esm-only-policy-add-esm-only-statement"
          },
          {
            "committed_at": 1786199146,
            "ref": "agent/gate-esm-cjs-guard-document-esm-only-policy-locate-esm-section",
            "sha": "a07b2407323ecf31f68ccf6392ac17c721f8cf77",
            "subject": "recovery-intent-stub: gate-esm-cjs-guard-document-esm-only-policy-locate-esm-section"
          },
          {
            "committed_at": 1786141725,
            "ref": "agent/gate-esm-cjs-guard-integrate-esm-linter-npm-test-test-cjs-file-detection",
            "sha": "a34450591421ede2a76eb415e436189444770afe",
            "subject": "recovery-intent-stub: gate-esm-cjs-guard-integrate-esm-linter-npm-test-test-cjs-file-detection"
          },
          {
            "committed_at": 1786161138,
            "ref": "agent/gate-esm-cjs-guard-integrate-esm-linter-npm-test-verify-lint-esm-script",
            "sha": "ca45ce421f73e3c03f15f6046fe5586eeca8b712",
            "subject": "recovery-intent-stub: recover-missing-branch-gate-esm-cjs-guard-integrate-esm-linter-npm-test-verify-lint-esm-script"
          },
          {
            "committed_at": 1786115392,
            "ref": "agent/qafix-pareto-2080-07062319-slice-1-slice-1-slice-2-patch-00ab3aa2c67a",
            "sha": "46563c7d7aef2416668a8c8b57d2473d21d437ab",
            "subject": "regen-from-cache(template): qafix-pareto-2080-07062319-slice-1-slice-1-slice-2-patch-00ab3aa2c67a"
          },
          {
            "committed_at": 1786117436,
            "ref": "agent/qafix-pareto-2080-07062319-slice-1-slice-1-slice-5",
            "sha": "5c78fb2258c5654598f3dfb676c01d132bada7e8",
            "subject": "patch-recovery: qafix-pareto-2080-07062319-slice-1-slice-1-slice-5"
          },
          {
            "committed_at": 1786118653,
            "ref": "agent/qafix-pareto-2080-07062319-slice-1-slice-2-repair-repo-setup",
            "sha": "407fd526401d73fc5336b7e8feaf357356c15b16",
            "subject": "regen-from-cache(template): qafix-pareto-2080-07062319-slice-1-slice-2-repair-repo-setup"
          },
          {
            "committed_at": 1786118739,
            "ref": "agent/qafix-pareto-2080-07062319-slice-1-slice-4-repair-repo-setup",
            "sha": "d9ec1a1fcd3ae7f6e3be9af250447c3156302d64",
            "subject": "regen-from-cache(template): qafix-pareto-2080-07062319-slice-1-slice-4-repair-repo-setup"
          },
          {
            "committed_at": 1786118800,
            "ref": "agent/qafix-pareto-2080-07062319-slice-5-add-agentledger-tests",
            "sha": "dd44aa8f74f4fe56236078faef44189c2910db84",
            "subject": "regen-from-cache(template): qafix-pareto-2080-07062319-slice-5-add-agentledger-tests"
          },
          {
            "committed_at": 1786118869,
            "ref": "agent/qafix-pareto-2080-07062319-slice-5-add-newutilities-tests",
            "sha": "60d2f7a27c92e948ac2026683a3a76b0edba962f",
            "subject": "patch-recovery: qafix-pareto-2080-07062319-slice-5-add-newutilities-tests"
          },
          {
            "committed_at": 1786118879,
            "ref": "agent/qafix-pareto-2080-07062319-slice-5-add-pricinggrid-tests",
            "sha": "8875019f3cb3e1337bbc31ba513f5155d848302b",
            "subject": "patch-recovery: qafix-pareto-2080-07062319-slice-5-add-pricinggrid-tests"
          },
          {
            "committed_at": 1786118947,
            "ref": "agent/qafix-pareto-2080-07062319-slice-5-fix-bookingsaga-test",
            "sha": "1501a6f1233548c338d180d6f0521ff892b2733f",
            "subject": "regen-from-cache(template): qafix-pareto-2080-07062319-slice-5-fix-bookingsaga-test"
          },
          {
            "committed_at": 1786161138,
            "ref": "agent/recover-missing-branch-gate-esm-cjs-guard-integrate-esm-linter-npm-test-verify-lint-esm-script",
            "sha": "ca45ce421f73e3c03f15f6046fe5586eeca8b712",
            "subject": "recovery-intent-stub: recover-missing-branch-gate-esm-cjs-guard-integrate-esm-linter-npm-test-verify-lint-esm-script"
          },
          {
            "committed_at": 1786117426,
            "ref": "agent/recover-missing-branch-qafix-pareto-2080-07062319-slice-1-slice-1-slice-5",
            "sha": "c94ac42bff35e9dbf3dead0e9db34aa373353551",
            "subject": "recovery-intent-stub: recover-missing-branch-qafix-pareto-2080-07062319-slice-1-slice-1-slice-5"
          },
          {
            "committed_at": 1786133889,
            "ref": "agent/rework-secret-experience-passport-3765ba6",
            "sha": "863c41828e1bc5b195412c61994bffe8cfde2bea",
            "subject": "patch-recovery: rework-secret-experience-passport-3765ba6"
          },
          {
            "committed_at": 1786417420,
            "ref": "fix/ria-enabled-gate-20260811",
            "sha": "5b56e41625e08ce5863dfbdf004647062a06f450",
            "subject": "fix(compliance): RIA_ENABLED fail-closed gate on portfolio advice [R1]"
          }
        ],
        "count": 30,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/pareto/2080"
      }
    ]
