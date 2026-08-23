PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-656c0680da0f
  title: Reconcile local ChatGPT/Codex build evidence for beethoven
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
    `656c0680da0f2400be32de9cd371cea2563016018c5a22051bc98baa02e5db66`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches_digest": "bfabbd7bada65811b82b032aee10450e1e00dc13532d8ad34afd6e1571758544",
        "branches_sample": [
          {
            "committed_at": 1786941176,
            "ref": "agent/backlog-batch-beethoven-22ee5bc-remaining-stale-backlog-items",
            "sha": "6993006d297a76bf4ed6b4f043ad153945179ae7",
            "subject": "agent: chatgpt-local-reconcile-beethoven-e0945946bd0d"
          },
          {
            "committed_at": 1786923368,
            "ref": "agent/backlog-batch-beethoven-7371e3f-add-bandit-prompt--slice-4-add-decay-formula-to-",
            "sha": "8c3a1cf357d518c80a89e75fb317323cca5495af",
            "subject": "agent: backlog-batch-beethoven-7371e3f-add-bandit-prompt--slice-4-add-decay-formula-to-"
          },
          {
            "committed_at": 1786922424,
            "ref": "agent/backlog-batch-beethoven-d3151d8",
            "sha": "85722e44d9d9090215fe159bc99a5a83bf176d1c",
            "subject": "agent: backlog-batch-beethoven-d3151d8"
          },
          {
            "committed_at": 1786923003,
            "ref": "agent/backlog-batch-beethoven-e63dfee-apply-orch-config-consumption-patch",
            "sha": "27de2d184e553d60a6545e5ea37c9e6e54fee776",
            "subject": "agent: backlog-batch-beethoven-e63dfee-apply-orch-config-consumption-patch"
          },
          {
            "committed_at": 1786946320,
            "ref": "agent/canary-codex-58-finalize-and-commit-commit-and-push-fixes",
            "sha": "72e5214780942e243e8c0f392dfcfecfe137edd0",
            "subject": "agent: dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat"
          },
          {
            "committed_at": 1786603734,
            "ref": "agent/canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-logging",
            "sha": "7e75c495241a470ae4dd5ff182f0c4b64f9e5fbc",
            "subject": "agent: canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-logging"
          },
          {
            "committed_at": 1786945010,
            "ref": "agent/chatgpt-local-reconcile-beethoven-16041039dfad",
            "sha": "5216eea695e23df515e2cb202d31929105395592",
            "subject": "agent: chatgpt-local-reconcile-beethoven-16041039dfad \u2014 rebuilt ledger-only on current master to clear the merge conflict"
          },
          {
            "committed_at": 1786940795,
            "ref": "agent/chatgpt-local-reconcile-beethoven-179a43b4d07a",
            "sha": "544b53530b96699d18c227f3077468c65fffc3a2",
            "subject": "agent: chatgpt-local-reconcile-beethoven-179a43b4d07a"
          },
          {
            "committed_at": 1786945260,
            "ref": "agent/chatgpt-local-reconcile-beethoven-3b50d1e569de",
            "sha": "dbbf7ca9e1506bc4cb71761f3810c258d55189fc",
            "subject": "agent: chatgpt-local-reconcile-beethoven-3b50d1e569de \u2014 rebuilt on current master to clear the merge conflict"
          },
          {
            "committed_at": 1786945150,
            "ref": "agent/chatgpt-local-reconcile-beethoven-48ada8033590",
            "sha": "07f85156cc58dc6ecfc724de5d7ca5174d9e4bed",
            "subject": "agent: chatgpt-local-reconcile-beethoven-48ada8033590 \u2014 rebuilt on current master to clear the merge conflict"
          },
          {
            "committed_at": 1786947734,
            "ref": "agent/chatgpt-local-reconcile-beethoven-53fd7e424376",
            "sha": "dbb4100a6d833a66cf7d0179fbd6ae610f1748a8",
            "subject": "agent: chatgpt-local-reconcile-beethoven-53fd7e424376"
          },
          {
            "committed_at": 1786943694,
            "ref": "agent/chatgpt-local-reconcile-beethoven-55acd60c79b1",
            "sha": "18c6d2e990c4535fa7d639b17bca8b0d75285d44",
            "subject": "agent: chatgpt-local-reconcile-beethoven-55acd60c79b1"
          },
          {
            "committed_at": 1786940719,
            "ref": "agent/chatgpt-local-reconcile-beethoven-671c267eedf3",
            "sha": "d7cefebee63ff4509d11d0f0783dcdd44c177252",
            "subject": "agent: chatgpt-local-reconcile-beethoven-671c267eedf3"
          },
          {
            "committed_at": 1786941071,
            "ref": "agent/chatgpt-local-reconcile-beethoven-6c8911116873",
            "sha": "b0b122de5d132c5a976105f561699c2a581b3752",
            "subject": "agent: chatgpt-local-reconcile-beethoven-6c8911116873"
          },
          {
            "committed_at": 1786945210,
            "ref": "agent/chatgpt-local-reconcile-beethoven-73b0c02a3342",
            "sha": "e95f5016dde5950cfe04d3a82b736a63b806e9d1",
            "subject": "agent: chatgpt-local-reconcile-beethoven-73b0c02a3342 \u2014 rebuilt on current master to clear the merge conflict"
          },
          {
            "committed_at": 1786940662,
            "ref": "agent/chatgpt-local-reconcile-beethoven-7bd5c9d0be16",
            "sha": "8445b70ee77a7f1c19ba7f1465c8733a168da557",
            "subject": "agent: chatgpt-local-reconcile-beethoven-7bd5c9d0be16"
          },
          {
            "committed_at": 1786942704,
            "ref": "agent/chatgpt-local-reconcile-beethoven-85d2de799d5d",
            "sha": "77f1da03bfb6fc61b2bcd488e1988c3a05b23e87",
            "subject": "agent: chatgpt-local-reconcile-beethoven-85d2de799d5d"
          },
          {
            "committed_at": 1786945111,
            "ref": "agent/chatgpt-local-reconcile-beethoven-9b427697d13f",
            "sha": "a24eadd2fa05cdc7e296e72e19655b817bad2ce3",
            "subject": "agent: chatgpt-local-reconcile-beethoven-9b427697d13f \u2014 rebuilt ledger-only on current master to clear the merge conflict"
          },
          {
            "committed_at": 1786943582,
            "ref": "agent/chatgpt-local-reconcile-beethoven-ee86a2cff698",
            "sha": "91d6c96423c46db4990150f13cdb0f151f4c5ebb",
            "subject": "agent: chatgpt-local-reconcile-beethoven-ee86a2cff698 \u2014 3/3 classified, 0 unknown; orphaned-worktree detection"
          },
          {
            "committed_at": 1786140994,
            "ref": "agent/copyfix-beethoven-07180848-slice-3-public-landing-founder-navigation-copy-clean-140991",
            "sha": "37a6932a8bf6b9182517d8e8405f8521fc8e5fc7",
            "subject": "self-heal: clean files from agent/copyfix-beethoven-07180848-slice-3-public-landing-founder-navigation-copy (31 files)"
          },
          {
            "committed_at": 1786654384,
            "ref": "agent/dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5",
            "sha": "ae0c9da50e7cbb07a1ed8be009f5057b16d513a8",
            "subject": "agent: dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5"
          },
          {
            "committed_at": 1786946269,
            "ref": "agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-1-never-again-lane-daemon-immune-system-p0-recovered",
            "sha": "7593cadee2eb6c62c890dc1b3e8d61fae6fb6613",
            "subject": "agent: dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-1-never-again-lane-daemon-immune-system-p0-recovered"
          },
          {
            "committed_at": 1786129454,
            "ref": "agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448",
            "sha": "358297faa18ff03172ac9f7240ce981e825e13bb",
            "subject": "self-heal: clean files from agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2 (18 files)"
          },
          {
            "committed_at": 1786058165,
            "ref": "agent/dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2",
            "sha": "60d1a6c325b3f7ae94bbd7c778b12baf56406ae0",
            "subject": "agent: dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2"
          },
          {
            "committed_at": 1786946320,
            "ref": "agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat",
            "sha": "72e5214780942e243e8c0f392dfcfecfe137edd0",
            "subject": "agent: dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat"
          },
          {
            "committed_at": 1785388122,
            "ref": "agent/dropbox-prediction-markets-institute-think-tank-launch-brand-exam-ap-contracts",
            "sha": "952bdd1b1838b886887137c0ccfcdcc52f24e148",
            "subject": "refactor(pricing-grid): extract capacity and consumption helpers to eliminate duplication"
          },
          {
            "committed_at": 1786943936,
            "ref": "agent/dropbox-prompt-merged-diff-memory-system-task-spec-group-19-wire-merge-detection",
            "sha": "c53c25ba224e71677d57bfde20b44300a256d5d9",
            "subject": "agent: dropbox-prompt-merged-diff-memory-system-task-spec-group-19-wire-merge-detection \u2014 wire merge detection into merged-diff memory"
          },
          {
            "committed_at": 1786946320,
            "ref": "agent/dropbox-wave-c-compounding-codegen-platform-spine--slice-5-rebase-and-verify",
            "sha": "72e5214780942e243e8c0f392dfcfecfe137edd0",
            "subject": "agent: dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat"
          },
          {
            "committed_at": 1786940926,
            "ref": "agent/improve-compliance-scheduling-observability",
            "sha": "bd07e84ac33dfda6159f48acadbcd14c4d7ce4c1",
            "subject": "agent: improve-compliance-scheduling-observability (rebuilt on current master; readiness stays behind auth)"
          },
          {
            "committed_at": 1787025107,
            "ref": "agent/improve-immediate-auto-merge-on-test-pass-low-r-slice-3-switch-scheduling-from-h",
            "sha": "521f5a7e931fdc9f87495291bfaa0e0f17432ce0",
            "subject": "agent: improve-immediate-auto-merge-on-test-pass-low-r-slice-3-switch-scheduling-from-h"
          }
        ],
        "branches_total": 42,
        "count": 42,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      },
      {
        "count": 576,
        "items_digest": "b21d3bdf7591746d224a0705548d6f96493fa0e333db2c10488637f725049e2b",
        "items_sample": [
          {
            "created_at": 1785715636,
            "ref": "refs/orch-rescue/20260803T000716-claude-orchestrator",
            "sha": "685bec47743acd2a3a650e4c7f9292b8da075ef6",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715638,
            "ref": "refs/orch-rescue/20260803T000718-breach-remediation",
            "sha": "72bc7ddf1f86a063743b4580974bad1edd05773e",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715639,
            "ref": "refs/orch-rescue/20260803T000719-cade-mirror-negotiation",
            "sha": "696872815d7128b21fb39251cb0dcdf24f766b14",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715640,
            "ref": "refs/orch-rescue/20260803T000720-cc-legacy-margin-removal",
            "sha": "c3d1aa9ea875f4dce9cda820a56c07e55df4aaf4",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715641,
            "ref": "refs/orch-rescue/20260803T000721-cc-mutual-default-fund",
            "sha": "54cb2405c801e47bbd126a557b3493a7463f20ce",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715641,
            "ref": "refs/orch-rescue/20260803T000721-cc-solvency-passport",
            "sha": "cb458638f92ba1b17d86374a7a5961218fa7c224",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715642,
            "ref": "refs/orch-rescue/20260803T000722-convention-conformance-lints",
            "sha": "7530399a51075888d1cbc54c2e5ff897861339e6",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715643,
            "ref": "refs/orch-rescue/20260803T000723-economic-scheduler-revenue",
            "sha": "c23fdeee475de01cec3dd8ec5a4e5e4707ddbfd1",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715644,
            "ref": "refs/orch-rescue/20260803T000724-ext-streaming-terms",
            "sha": "93d532b1c586551809cbba6fe4f035a30ae358bb",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715644,
            "ref": "refs/orch-rescue/20260803T000724-hive-enforcement-velocity-index",
            "sha": "62602aee6fc65c27dc908f8cb07f456ba986f4c9",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715644,
            "ref": "refs/orch-rescue/20260803T000724-merged-diff-memory",
            "sha": "791ce633eed2c06eb9ad96761c0d011e12e5ad4a",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-oc-autoclear-policy",
            "sha": "4202f5b49f2d8b000f169405afd22f90aef70fee",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-orch-config-consumption",
            "sha": "0bee7ff2f1f351dfbe792245978ccd61a70ce238",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-pinned-express-lane",
            "sha": "5f3ed25ef56f6cf9eed2cff816e69bf310dd1d62",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715645,
            "ref": "refs/orch-rescue/20260803T000725-ploeh-s2s-bridge-tomorrow",
            "sha": "17646f8e58bcc9b86e77bfd282d0bf6dd0fe9efe",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715646,
            "ref": "refs/orch-rescue/20260803T000726-prompt-evolution-bandit",
            "sha": "c724ed32431eeaac9d26c743e5ba0f4892347e7c",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715646,
            "ref": "refs/orch-rescue/20260803T000726-relfix-racefeed-07060650-slice-4",
            "sha": "9c023d06b7446d5d97e539979a17e47af66415cb",
            "subject": "On fix-branch: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-breach-remediation",
            "sha": "1ae53af0304da13115a858c5607694cfb32766c8",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cade-mirror-negotiation",
            "sha": "730ac4d5e6b5e53339572abd4b91077d577e197b",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cc-legacy-margin-removal",
            "sha": "eb0f0cb53cb34c4fef57810a6008feeaf9b85b29",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cc-mutual-default-fund",
            "sha": "ef9819ce0821ec013c54c9f1cfcab52fe775aa8e",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-cc-solvency-passport",
            "sha": "f87dd5880750cec7466c87ac4e3d359333218d5e",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-claude-orchestrator",
            "sha": "297045a4747551df5dc2c6b7a808782ec162b940",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-convention-conformance-lints",
            "sha": "e4939832797b20ae7a32ea5286eca04cfc717c35",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715671,
            "ref": "refs/orch-rescue/20260803T000751-economic-scheduler-revenue",
            "sha": "4b70e54e5e84d811e0ea757cc30145b55fa8c90d",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-ext-streaming-terms",
            "sha": "1a057825f68bdbee67f2d25267c09be86fbf6374",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-hive-enforcement-velocity-index",
            "sha": "c9f3f13cb65d42652b97e9acf8fc14fc49722866",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-merged-diff-memory",
            "sha": "6224b1d8130f62992bc7cd2f721d7ef57f843b9c",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-oc-autoclear-policy",
            "sha": "925cb1cb72c51d8a8f873f18594ffcb9a448adda",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715672,
            "ref": "refs/orch-rescue/20260803T000752-orch-config-consumption",
            "sha": "8e413e3adb3c0a79d7bf19953aac661c094e2f46",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 576,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      },
      {
        "count": 2,
        "items": [
          {
            "created_at": 1787026208,
            "ref": "stash@{2}",
            "sha": "a9f38fd798b8ffbffb9725191bfb66c90ac77187",
            "subject": "WIP on master: 2acd4139 Add comprehensive tests for opportunity_scout.py RICE scoring and proposal filing"
          },
          {
            "created_at": 1787011491,
            "ref": "stash@{3}",
            "sha": "6ca51b977b01731c37d8e975f4015ba3aff66a28",
            "subject": "WIP on master: e5c6c5bf docs: top 3 highest-leverage opportunities from runner codebase scan (RICE-scored)"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
