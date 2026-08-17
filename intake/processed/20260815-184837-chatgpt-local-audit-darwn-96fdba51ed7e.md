PROJECT: darwn

- id: chatgpt-local-reconcile-darwn-96fdba51ed7e
  title: Reconcile local ChatGPT/Codex build evidence for darwn
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
    `96fdba51ed7ef7afeadb0caf3bad971b87a49f1fb2079a4ca182c0c52f9cd870`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "main",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "bf1b547d511c1eaa97e2d9f2c3cc79e55078cd52",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786796249,
        "path": "/Users/kpasch/Documents/darwn/darwn"
      },
      {
        "branches_digest": "5f7856f9402d333b50867a86745c0828143c30295f4122f8330e21c112a12689",
        "branches_sample": [
          {
            "committed_at": 1786074672,
            "ref": "agent/backlog-batch-darwn-5b34a9d-slice-2-cade-firm-opponent-models-transplant-selecte",
            "sha": "16caf9aac69ed5c2b365a03bf680116f297d97ad",
            "subject": "regen-from-cache(template): backlog-batch-darwn-5b34a9d-slice-2-cade-firm-opponent-models-transplant-selecte"
          },
          {
            "committed_at": 1786119296,
            "ref": "agent/backlog-batch-darwn-611fabe-remediate-cont-2249c9-5ca240-test-and-co",
            "sha": "96470b3adf5be1a0de132ac8c7def26a4de9dfc6",
            "subject": "regen-from-cache(template): backlog-batch-darwn-611fabe-remediate-cont-2249c9-5ca240-test-and-co"
          },
          {
            "committed_at": 1786137061,
            "ref": "agent/backlog-batch-darwn-d2c0780-darwn-batch-processor",
            "sha": "4d621983c6c62264a87044d5974c103f590540b6",
            "subject": "recovery-intent-stub: backlog-batch-darwn-d2c0780-darwn-batch-processor"
          },
          {
            "committed_at": 1786136130,
            "ref": "agent/canary-darwn-20260713-slice-1-implement-duplicate-removal-mechanism",
            "sha": "c5b2f3a8edb2d549ffa44a0bc064581dc0dd2618",
            "subject": "recovery-intent-stub: canary-darwn-20260713-slice-1-implement-duplicate-removal-mechanism"
          },
          {
            "committed_at": 1786141607,
            "ref": "agent/canary-darwn-20260713-slice-4-implement-behavior",
            "sha": "698609892cefa346d22becebd26da548daaf3351",
            "subject": "recovery-intent-stub: canary-darwn-20260713-slice-4-implement-behavior"
          },
          {
            "committed_at": 1786141411,
            "ref": "agent/canary-darwn-20260713-slice-4-locate-existing-owner-module",
            "sha": "99d96075ef9c7fd5d0f246de3882ebec18a269d5",
            "subject": "recovery-intent-stub: canary-darwn-20260713-slice-4-locate-existing-owner-module"
          },
          {
            "committed_at": 1785868283,
            "ref": "agent/canary-darwn-20260725",
            "sha": "d16c4fc6186a0ccac22cb5896cd649e18abd9c69",
            "subject": "fix: canary-darwn-20260725 \u2014 fail-soft infra handling in rating validation"
          },
          {
            "committed_at": 1786152567,
            "ref": "agent/canary-darwn-20260726-implement-canary-heartbeat-touch",
            "sha": "125cf9b020a119ebc224c074bb85b4191d0cd249",
            "subject": "recovery-intent-stub: canary-darwn-20260726-implement-canary-heartbeat-touch"
          },
          {
            "committed_at": 1786795630,
            "ref": "agent/chatgpt-local-reconcile-darwn-04b0022358d1",
            "sha": "433f783ff231d9038a471e24eafd902befe82fbd",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-darwn-04b0022358d1"
          },
          {
            "committed_at": 1786654063,
            "ref": "agent/chatgpt-local-reconcile-darwn-87db0cc80434",
            "sha": "329c2c6a1de38b3ef70206a05f3aa2a99a62f3ff",
            "subject": "agent: chatgpt-local-reconcile-darwn-87db0cc80434"
          },
          {
            "committed_at": 1786794337,
            "ref": "agent/chatgpt-local-reconcile-darwn-99b3c3bd9840",
            "sha": "2b7d6173f0673f81ce9a726540f2569bf1bb809c",
            "subject": "agent: chatgpt-local-reconcile-darwn-99b3c3bd9840"
          },
          {
            "committed_at": 1786796080,
            "ref": "agent/chatgpt-local-reconcile-darwn-bdb0cfed9b14",
            "sha": "dfbe8314daff11e36fdcb352060fea1b679f8b6e",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-darwn-bdb0cfed9b14"
          },
          {
            "committed_at": 1786654034,
            "ref": "agent/chatgpt-local-reconcile-darwn-cba9a5a9cf54",
            "sha": "1acecb066766355928be0f19f4610afae1c236ed",
            "subject": "agent: chatgpt-local-reconcile-darwn-cba9a5a9cf54"
          },
          {
            "committed_at": 1786794387,
            "ref": "agent/chatgpt-local-reconcile-darwn-d11e8740c03a",
            "sha": "75a3250fd9aa0610b00b2f33506f5af021dd0b24",
            "subject": "agent: chatgpt-local-reconcile-darwn-d11e8740c03a"
          },
          {
            "committed_at": 1786654047,
            "ref": "agent/chatgpt-local-reconcile-darwn-d669a6457336",
            "sha": "de2d48ef928309ec043d07fffeeda3ac2e33df71",
            "subject": "agent: chatgpt-local-reconcile-darwn-d669a6457336"
          },
          {
            "committed_at": 1786654078,
            "ref": "agent/chatgpt-local-reconcile-darwn-db2e16927651",
            "sha": "3a3de6f19a2427dc7ef8277d70d968cd7c2a5f1e",
            "subject": "agent: chatgpt-local-reconcile-darwn-db2e16927651"
          },
          {
            "committed_at": 1786796336,
            "ref": "agent/chatgpt-local-reconcile-darwn-eaa3ab08eac9",
            "sha": "1bfb42c450db903b8b98ae9006ade667f1a5e80a",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-darwn-eaa3ab08eac9"
          },
          {
            "committed_at": 1786591234,
            "ref": "agent/dropbox-darwn-reconcile-darwinlife-repo-ownership",
            "sha": "dd84119fa3f5d27be7002287b4b893b53186a5c5",
            "subject": "agent: dropbox-darwn-reconcile-darwinlife-repo-ownership"
          },
          {
            "committed_at": 1786590459,
            "ref": "agent/dropbox-darwn-reconcile-enumerate-stashes",
            "sha": "93c5bae79f09a3773a43cf2981c11f293f3ebc01",
            "subject": "agent: dropbox-darwn-reconcile-enumerate-stashes"
          },
          {
            "committed_at": 1786590377,
            "ref": "agent/dropbox-darwn-reconcile-recover-local-only-branch-tips",
            "sha": "98614bd8851151f443d09efaa233d3ef06cefea6",
            "subject": "agent: dropbox-darwn-reconcile-recover-local-only-branch-tips"
          },
          {
            "committed_at": 1786591166,
            "ref": "agent/dropbox-darwn-reconcile-recover-orchestrator-rescue-refs",
            "sha": "7653516bedc6a02b13bf3b1b1193eae5eb06aa1f",
            "subject": "agent: dropbox-darwn-reconcile-recover-orchestrator-rescue-refs"
          },
          {
            "committed_at": 1786593142,
            "ref": "agent/dropbox-darwn-rescue-adjudicate-rls-migrations",
            "sha": "06357f0d67ac97d7637fb57c00f1389734e3eb71",
            "subject": "agent: dropbox-darwn-rescue-adjudicate-rls-migrations"
          },
          {
            "committed_at": 1786593119,
            "ref": "agent/dropbox-darwn-rescue-recover-admin-patch-template",
            "sha": "f21c3388960fac8db7b53331889dc182b62f2c92",
            "subject": "test(toolchain): resolve pnpm-hoisted transitive deps so h3 importers can be tested"
          },
          {
            "committed_at": 1786590503,
            "ref": "agent/dropbox-darwn-rescue-recover-handoff-store",
            "sha": "d0f455b526850b055a9f114c6a94e173d4812bd3",
            "subject": "agent: dropbox-darwn-rescue-recover-handoff-store"
          },
          {
            "committed_at": 1786590554,
            "ref": "agent/dropbox-darwn-rescue-recover-market-patch",
            "sha": "7763da11e16fa056fea6f7bf63d2c59a9a789849",
            "subject": "agent: dropbox-darwn-rescue-recover-market-patch"
          },
          {
            "committed_at": 1786593111,
            "ref": "agent/dropbox-darwn-rescue-recover-model-env-gate",
            "sha": "f5786ca8123fd0d4dd745b966d799a2496145174",
            "subject": "agent: dropbox-darwn-rescue-recover-model-env-gate"
          },
          {
            "committed_at": 1786617809,
            "ref": "agent/dropbox-darwn-rescue-recover-ref-3a2b374",
            "sha": "848d909ad7d018248b8013bbed6f16401eaa34b3",
            "subject": "agent: dropbox-darwn-rescue-recover-ref-3a2b374"
          },
          {
            "committed_at": 1786636608,
            "ref": "agent/dropbox-darwn-rescue-recover-ref-7d9443b",
            "sha": "a832b15658aa90574c9ed7fdd0c407ff24d53d2b",
            "subject": "agent: dropbox-darwn-rescue-recover-ref-7d9443b"
          },
          {
            "committed_at": 1786636658,
            "ref": "agent/dropbox-darwn-rescue-recover-ref-9efa5f6",
            "sha": "d4c21b0869725bba63d3602239bb6f658df8df9c",
            "subject": "agent: dropbox-darwn-rescue-recover-ref-9efa5f6"
          },
          {
            "committed_at": 1786636620,
            "ref": "agent/dropbox-darwn-rescue-recover-ref-bef9208",
            "sha": "fdd2acb865b24a78ea2f77efe3c206cf066bf771",
            "subject": "agent: dropbox-darwn-rescue-recover-ref-bef9208"
          }
        ],
        "branches_total": 53,
        "count": 53,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      },
      {
        "count": 226,
        "items_digest": "9879d9fdcaa8bb149fd21bb2969aff9c9d36ff0461990bed2d6c174dd5e36735",
        "items_sample": [
          {
            "created_at": 1785715614,
            "ref": "refs/orch-rescue/20260803T000654-cade-mirror-negotiation",
            "sha": "dc03cd48d6657aaed8cf31c4c329a6e38da96a06",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715614,
            "ref": "refs/orch-rescue/20260803T000654-cc-legacy-margin-removal",
            "sha": "dda6bd2333efdb7c90618d97e99ecea2073bd23e",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715614,
            "ref": "refs/orch-rescue/20260803T000654-cc-mutual-default-fund",
            "sha": "e58e3c55632ee6a44493f61c5bbd1f949df2ea98",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715614,
            "ref": "refs/orch-rescue/20260803T000654-convention-conformance-lints",
            "sha": "a76377013d07921816a9f4207131a51683542232",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715614,
            "ref": "refs/orch-rescue/20260803T000654-darwn",
            "sha": "4f4bf432151adfa61c47ef2381dc100ea6a53500",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715614,
            "ref": "refs/orch-rescue/20260803T000654-economic-scheduler-revenue",
            "sha": "f87ad7be0a8c1571f61de0cf82405ca174ff1265",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715615,
            "ref": "refs/orch-rescue/20260803T000655-ensemble-on-hard",
            "sha": "a772f1b4b152fbc921b70d3a342de42a2c57fd1e",
            "subject": "On agent/ensemble-on-hard: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715615,
            "ref": "refs/orch-rescue/20260803T000655-hive-support-entity-relationship-source",
            "sha": "d175583f4784ddfb01b546a8ce373f081c10b8db",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715615,
            "ref": "refs/orch-rescue/20260803T000655-merged-diff-memory",
            "sha": "6e0e8bda523e079575fc9c2fc840a5780cfa2ef2",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715615,
            "ref": "refs/orch-rescue/20260803T000655-orch-config-consumption",
            "sha": "33e2de24748decb60aeb2aee52c3d836eed998a8",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715615,
            "ref": "refs/orch-rescue/20260803T000655-pinned-express-lane",
            "sha": "dfbdf2633f148c8b4cb91839e28ea3fc66c08ac3",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715616,
            "ref": "refs/orch-rescue/20260803T000656-ploeh-s2s-bridge-tomorrow",
            "sha": "358d09a39ed706d8ce6b3e9de93cc957c1e37d06",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715616,
            "ref": "refs/orch-rescue/20260803T000656-smarter-5-95",
            "sha": "95bb63aee5866e74eebc259cee3bf838825c7473",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-cade-mirror-negotiation",
            "sha": "c8d555444f7183fb4541e7a40957cf7a7b8f4de3",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-cc-legacy-margin-removal",
            "sha": "7a06e2edb4380fe9ad55a4b44f5a0f4df12bbbbf",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-cc-mutual-default-fund",
            "sha": "cf32b14b9ce6b74d25211c85653f9cba7288255c",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-darwn",
            "sha": "667450c75d86ba848d3f0954b6c49a508156662e",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-convention-conformance-lints",
            "sha": "064167ca49f64845e2a19dc8892a8ab36a2f813f",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-economic-scheduler-revenue",
            "sha": "76fddd6eb6f48f8aead04ce3ed2e6abe5779dbbb",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-ensemble-on-hard",
            "sha": "8f4fc8edac0f240282e82816fe16961b3fbaee42",
            "subject": "On agent/ensemble-on-hard: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-hive-support-entity-relationship-source",
            "sha": "67111dbc5cdc5ec15e4a856b7750aa2688e49952",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-merged-diff-memory",
            "sha": "8a3d59413c201603db5079d7de43883c03bc355f",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-orch-config-consumption",
            "sha": "32e4f493ae404c49f80d71c81873afba5566d5de",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-pinned-express-lane",
            "sha": "dd0b16cc150ec51cab1707ad662e50440f911508",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-ploeh-s2s-bridge-tomorrow",
            "sha": "ef3ce168d25e377dc1b5ce3b283d3ce3f9d7f7db",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-smarter-5-95",
            "sha": "dd81097e4d45414c79897c796e1df64041513d6b",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716110,
            "ref": "refs/orch-rescue/20260803T001510-cade-mirror-negotiation-fafdabac",
            "sha": "fafdabac39de6b3c5d9ff1dc51ff0f68bef76270",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716110,
            "ref": "refs/orch-rescue/20260803T001510-cc-legacy-margin-removal-a7f2fac2",
            "sha": "a7f2fac2ead525786f14040b1dd71a7a7882806d",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716110,
            "ref": "refs/orch-rescue/20260803T001510-cc-mutual-default-fund-b65ba7ca",
            "sha": "b65ba7cab728f57d8cd734927c0804794ce3c251",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716110,
            "ref": "refs/orch-rescue/20260803T001510-convention-conformance-lints-bed40d69",
            "sha": "bed40d691d82c3ef49525e3d5c3a43ee8810b65f",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 226,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      }
    ]
