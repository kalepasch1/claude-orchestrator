PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-135112e9fa83
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
    `135112e9fa83776b18b4e2b321218caa252eb64c70102433fef68498df808ca2`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches_digest": "db8cd364654573a8cf63cf8a4142593eff0b738c8f6ad7b12461877bb892cd72",
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
            "committed_at": 1786152447,
            "ref": "agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441",
            "sha": "dc65c5428c7ca2d3de8d2cf017ced6fa513e438c",
            "subject": "self-heal: clean files from agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a (30 files)"
          }
        ],
        "branches_total": 43,
        "count": 43,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
