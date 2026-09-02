PROJECT: smarter

- id: chatgpt-local-reconcile-smarter-c2a319ac2baf
  title: Reconcile local ChatGPT/Codex build evidence for smarter
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
    `c2a319ac2bafb7e08d6cb0a9c60eda5b7664f4e8a3a6ac9a54d1c793eedd6116`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "1ef2248cec5798c2bd399a9321bbfcd33eba321d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786236833,
        "path": "/private/tmp/merge-qa-fltng07z/candidate"
      },
      {
        "branches": [
          {
            "committed_at": 1786121959,
            "ref": "agent/backlog-batch-smarter-82f15de",
            "sha": "eafe369dcf954e799433414bbab111e7bbfdf127",
            "subject": "regen-from-cache(template): backlog-batch-smarter-82f15de"
          },
          {
            "committed_at": 1786116698,
            "ref": "agent/copyfix-smarter-07190105-slice-3",
            "sha": "a96112d5503740447937f118b9cc72b5b6aa5e86",
            "subject": "recovery-intent-stub: recover-missing-branch-copyfix-smarter-07190105-slice-3"
          },
          {
            "committed_at": 1786128033,
            "ref": "agent/qafix-smarter-9c3a08b5d8dd-adapt-merge-diff-pricinggrid-dedup-verify-changes",
            "sha": "26b7d46b34c4d07e5d78b156482bca7e500b172d",
            "subject": "salvage: interrupted work for qafix-smarter-9c3a08b5d8dd-adapt-merge-diff-pricinggrid-dedup-verify-changes"
          },
          {
            "committed_at": 1786129202,
            "ref": "agent/qafix-smarter-9c3a08b5d8dd-fix-htsparkline-ts-implicit-any-add-type-annotations",
            "sha": "c3970515e9fa82451328d47f0175403b2afe260d",
            "subject": "salvage: interrupted work for qafix-smarter-9c3a08b5d8dd-fix-htsparkline-ts-implicit-any-add-type-annotations"
          },
          {
            "committed_at": 1786130208,
            "ref": "agent/qafix-smarter-9c3a08b5d8dd-fix-htsparkline-ts-implicit-any-compile-file",
            "sha": "f25e19279284afe925ff7f2c95c5814fdeab363a",
            "subject": "salvage: interrupted work for qafix-smarter-9c3a08b5d8dd-fix-htsparkline-ts-implicit-any-compile-file"
          },
          {
            "committed_at": 1786116698,
            "ref": "agent/recover-missing-branch-copyfix-smarter-07190105-slice-3",
            "sha": "a96112d5503740447937f118b9cc72b5b6aa5e86",
            "subject": "recovery-intent-stub: recover-missing-branch-copyfix-smarter-07190105-slice-3"
          },
          {
            "committed_at": 1786116899,
            "ref": "agent/recover-missing-branch-remediate-weekly-lint-smarter-c5700f",
            "sha": "69a3e90c6d1c710fb547c1686d2a7dff49d406ef",
            "subject": "recovery-intent-stub: recover-missing-branch-remediate-weekly-lint-smarter-c5700f"
          },
          {
            "committed_at": 1786117087,
            "ref": "agent/recover-missing-branch-smarter-5-95-add-advanced-options-toggle",
            "sha": "3ff4b0a3af1c2f178cb4bb333249e18b13b1d360",
            "subject": "recovery-intent-stub: recover-missing-branch-smarter-5-95-add-advanced-options-toggle"
          },
          {
            "committed_at": 1786116952,
            "ref": "agent/recover-missing-branch-smarter-5-95-implement-strict-decision-budget",
            "sha": "293c2bba36f57b03eb53d53c9e988ae88672be92",
            "subject": "recovery-intent-stub: recover-missing-branch-smarter-5-95-implement-strict-decision-budget"
          },
          {
            "committed_at": 1786118378,
            "ref": "agent/relfix-smarter-07182307-integrate-patch-add-patch-integration-tests",
            "sha": "f124507884ce3c5925d8277321721c515a19b461",
            "subject": "regen-from-cache(template): relfix-smarter-07182307-integrate-patch-add-patch-integration-tests"
          },
          {
            "committed_at": 1786117087,
            "ref": "agent/smarter-5-95-add-advanced-options-toggle",
            "sha": "3ff4b0a3af1c2f178cb4bb333249e18b13b1d360",
            "subject": "recovery-intent-stub: recover-missing-branch-smarter-5-95-add-advanced-options-toggle"
          },
          {
            "committed_at": 1786116952,
            "ref": "agent/smarter-5-95-implement-strict-decision-budget",
            "sha": "293c2bba36f57b03eb53d53c9e988ae88672be92",
            "subject": "recovery-intent-stub: recover-missing-branch-smarter-5-95-implement-strict-decision-budget"
          },
          {
            "committed_at": 1784950301,
            "ref": "canary-pipeline-heartbeat-20260724",
            "sha": "5ada2f0ba346a788339cddf5135db672e9d516e2",
            "subject": "chore: pipeline heartbeat canary for 2026-07-24"
          },
          {
            "committed_at": 1787010785,
            "ref": "orchestrator/dev",
            "sha": "6f93d1eae7d8f56534c9e0c675681b5cc4a76ea9",
            "subject": "feat(lint): enforce strict decision budgets for three high-stakes surfaces"
          }
        ],
        "count": 14,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/smarter"
      },
      {
        "count": 272,
        "items_digest": "54d2ef032915ce42c746d33dc363ce3705a6cab53983cf85dec5e615d38833b2",
        "items_sample": [
          {
            "created_at": 1785715647,
            "ref": "refs/orch-rescue/20260803T000727-breach-remediation",
            "sha": "9b3148de2f99d13574659b61ea24047d15048d82",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715647,
            "ref": "refs/orch-rescue/20260803T000727-cade-mirror-negotiation",
            "sha": "95fe86f5311205dd387c844f58d1215df3b8a2c0",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715647,
            "ref": "refs/orch-rescue/20260803T000727-cc-legacy-margin-removal",
            "sha": "71bd1fbfb0bc3f24bab62bba5d4ea651918dcf8f",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715647,
            "ref": "refs/orch-rescue/20260803T000727-smarter",
            "sha": "10530a6210789087de3d7965deeaa1bafc3cd136",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715648,
            "ref": "refs/orch-rescue/20260803T000728-cc-mutual-default-fund",
            "sha": "a18c29c29c0a901f0d0a25d169a4201b670e33ed",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715648,
            "ref": "refs/orch-rescue/20260803T000728-cc-solvency-passport",
            "sha": "632e8ba21c21bd71428ff025bb1bdd15e0ca99fb",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785683216,
            "ref": "refs/orch-rescue/20260803T000728-consensus-engine-spec-fix-auto-filer-409-handler",
            "sha": "b594891854e9a33e23b93fe197b132ae4d6b9ee0",
            "subject": "agent: consensus-engine-spec-fix-auto-filer-409-handler"
          },
          {
            "created_at": 1785715648,
            "ref": "refs/orch-rescue/20260803T000728-convention-conformance-lints",
            "sha": "e6819f3735624f97427c187309d8f13043113b59",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715648,
            "ref": "refs/orch-rescue/20260803T000728-hive-enforcement-velocity-index",
            "sha": "90781eee55b5bdfa7d75410bb4d1e819753ad1b8",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715648,
            "ref": "refs/orch-rescue/20260803T000728-hive-support-entity-relationship-source",
            "sha": "a94354ed905a225b223430815672bf2b117a04ba",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715648,
            "ref": "refs/orch-rescue/20260803T000728-merged-diff-memory",
            "sha": "07d83c096db241ae386eb1a076702f3a18121109",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715649,
            "ref": "refs/orch-rescue/20260803T000729-orch-config-consumption",
            "sha": "57818828bef5b0ebe15221b043d7db56b2e4da62",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715649,
            "ref": "refs/orch-rescue/20260803T000729-pinned-express-lane",
            "sha": "5f39034c4d5416c86ae21d49af5f983bb70e579d",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715649,
            "ref": "refs/orch-rescue/20260803T000729-ploeh-s2s-bridge-tomorrow",
            "sha": "abd08b5d9e6de2e2d1b5941c6feb230729427b25",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715649,
            "ref": "refs/orch-rescue/20260803T000729-prompt-evolution-bandit",
            "sha": "bcc402754b6e4d046f0c64d9c523f29d6b294f1a",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715673,
            "ref": "refs/orch-rescue/20260803T000753-breach-remediation",
            "sha": "b1bc57fa57f47181f4126177d0afa720b3e05eff",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715673,
            "ref": "refs/orch-rescue/20260803T000753-cade-mirror-negotiation",
            "sha": "3bd43d43816a55688976fe6933755b452598531f",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715673,
            "ref": "refs/orch-rescue/20260803T000753-cc-legacy-margin-removal",
            "sha": "d2cb93bca37e97c0082270caffee1c8ff29174e5",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715673,
            "ref": "refs/orch-rescue/20260803T000753-cc-mutual-default-fund",
            "sha": "840092e5647509cd95693bcc1b21864db7824ccb",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715673,
            "ref": "refs/orch-rescue/20260803T000753-cc-solvency-passport",
            "sha": "1c7964bb400c10a2d4fcd940706a3c70c6a67e95",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785683216,
            "ref": "refs/orch-rescue/20260803T000753-consensus-engine-spec-fix-auto-filer-409-handler",
            "sha": "b594891854e9a33e23b93fe197b132ae4d6b9ee0",
            "subject": "agent: consensus-engine-spec-fix-auto-filer-409-handler"
          },
          {
            "created_at": 1785715673,
            "ref": "refs/orch-rescue/20260803T000753-convention-conformance-lints",
            "sha": "5f6edce4dff4349214efedfe597ab3b231b5786e",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715673,
            "ref": "refs/orch-rescue/20260803T000753-hive-enforcement-velocity-index",
            "sha": "4f3adc78f14f8fe780f302e4140fb5cc2c95b13e",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715673,
            "ref": "refs/orch-rescue/20260803T000753-hive-support-entity-relationship-source",
            "sha": "c4bfcd669d850e722fd4ab91d170204e189215a3",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715673,
            "ref": "refs/orch-rescue/20260803T000753-smarter",
            "sha": "d45e5218693d18f2fe1e4ca24473bf26104a763b",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715674,
            "ref": "refs/orch-rescue/20260803T000754-merged-diff-memory",
            "sha": "38117b3e40e666679df759ec93f6bda7d507359d",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715674,
            "ref": "refs/orch-rescue/20260803T000754-orch-config-consumption",
            "sha": "3a26b922ff42ece33959caea596f25af0a36dc64",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715674,
            "ref": "refs/orch-rescue/20260803T000754-pinned-express-lane",
            "sha": "ac99de136e6b2451b5cef84ef89c42feb0385619",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715674,
            "ref": "refs/orch-rescue/20260803T000754-ploeh-s2s-bridge-tomorrow",
            "sha": "8d483f8369e9443ac77108235bc801cdac1774b8",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715674,
            "ref": "refs/orch-rescue/20260803T000754-prompt-evolution-bandit",
            "sha": "308783ed8fb52524eed335d923943235a3f30ea9",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 272,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/smarter"
      }
    ]
