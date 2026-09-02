PROJECT: darwn

- id: chatgpt-local-reconcile-darwn-3b522e7475ae
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
    `3b522e7475ae3481671b521dfefa4faa2b1d6696d6698df21af7db0aed99f749`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/counterfactual-replay",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "bf1b547d511c1eaa97e2d9f2c3cc79e55078cd52",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787094578,
        "path": "/Users/kpasch/Documents/darwn/darwn-wt/counterfactual-replay"
      },
      {
        "branch": "agent/session-proof-of-work",
        "change_count": 1,
        "changes": [
          "package-lock.json"
        ],
        "changes_digest": "e7cd2b119de9d966cdbaf4de659cb798610e6475e0defbeb4885209f501bb8bb",
        "head": "655b6e91919f736150b23c1859331e3caadd4672",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787094602,
        "path": "/Users/kpasch/Documents/darwn/darwn-wt/session-proof-of-work"
      },
      {
        "count": 261,
        "items_digest": "f5d1ee1cd238b4f1d1a4d1fb6b7eed0b8815d3a055085a2166afa2acd8063f53",
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
        "items_total": 261,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      }
    ]
