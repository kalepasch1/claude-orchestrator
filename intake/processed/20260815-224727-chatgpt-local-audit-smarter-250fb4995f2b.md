PROJECT: smarter

- id: chatgpt-local-reconcile-smarter-250fb4995f2b
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
    `250fb4995f2bae31d4e58428bc88965ab7fe47e199704c4cff11a54098cb0402`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 267,
        "items_digest": "c772671fe2e6aea1285f685c6967f85b40cb7ede81b361647aff0cb206de84a6",
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
            "created_at": 1785715650,
            "ref": "refs/orch-rescue/20260803T000730-smarter-5-95",
            "sha": "de55e28a664755802ad3ba43e4f8f7d4f9914aad",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
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
          }
        ],
        "items_total": 267,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/smarter"
      }
    ]
