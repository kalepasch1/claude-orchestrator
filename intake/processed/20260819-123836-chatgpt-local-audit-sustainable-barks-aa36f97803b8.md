PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-aa36f97803b8
  title: Reconcile local ChatGPT/Codex build evidence for sustainable-barks
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
    `aa36f97803b89efcd63f35ba470bf5cf917cf88a282a732f0c9e0bf74e6ddc00`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 224,
        "items_digest": "071e816b54d74fd6ea62fd63650b0ba66891041380a7e0a5611aa434c2e0af9f",
        "items_sample": [
          {
            "created_at": 1785715612,
            "ref": "refs/orch-rescue/20260803T000652-Sustainable_Barks",
            "sha": "8661905f8a9d7404e3f1c89332670fcb276b95c6",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715613,
            "ref": "refs/orch-rescue/20260803T000653-cade-mirror-negotiation",
            "sha": "46b24e5da4e35808cb9e92f436250d3884ec4839",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715613,
            "ref": "refs/orch-rescue/20260803T000653-cc-legacy-margin-removal",
            "sha": "bb1d91e709259977906f93348939538783b015bf",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715613,
            "ref": "refs/orch-rescue/20260803T000653-hive-support-entity-relationship-source",
            "sha": "718e1b77643ff157bf802607bfc90a21754168e9",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715613,
            "ref": "refs/orch-rescue/20260803T000653-merge-legacy-agent-funding-equilibrium",
            "sha": "cf774a8694b03c798f6d303561b0c23ebdce615d",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715613,
            "ref": "refs/orch-rescue/20260803T000653-pinned-express-lane",
            "sha": "2e4708c73f2c9af08c463be388d69c2d24eb277c",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715613,
            "ref": "refs/orch-rescue/20260803T000653-prompt-evolution-bandit",
            "sha": "17f0dd94c095399ffd0dcdc17e330625321d0285",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-Sustainable_Barks",
            "sha": "896e94f9b57c3c504a371f71e559113aff6f635a",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-cade-mirror-negotiation",
            "sha": "cc6f8e719359f0157fb6a0376c731412c536816b",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-cc-legacy-margin-removal",
            "sha": "dfb0111d3fb4b904b05f5123370f8f1ce643d6c4",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-hive-support-entity-relationship-source",
            "sha": "41d79209b121ca07fddc49a63a223463ed54ec1e",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-merge-legacy-agent-funding-equilibrium",
            "sha": "516833579464da4c4d22ff077cf75d66d96faff8",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-pinned-express-lane",
            "sha": "d44a12a5ed90f16de8846728108f5b2d1cb3ae1a",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715663,
            "ref": "refs/orch-rescue/20260803T000743-prompt-evolution-bandit",
            "sha": "d205bf4f246a8b27eccbea2a2b2a2b896a02ee03",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716109,
            "ref": "refs/orch-rescue/20260803T001509-cade-mirror-negotiation-1e1c9331",
            "sha": "1e1c933185be8731df5c98d7ed50ce42949a5ac1",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716109,
            "ref": "refs/orch-rescue/20260803T001509-cc-legacy-margin-removal-88c0494a",
            "sha": "88c0494aaf8a3c263fce876ccc5483992710fedb",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716109,
            "ref": "refs/orch-rescue/20260803T001509-hive-support-entity-relationship-source-0b5b279a",
            "sha": "0b5b279a8cb78276a11344bb9140abd00e689c79",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716109,
            "ref": "refs/orch-rescue/20260803T001509-merge-legacy-agent-funding-equilibrium-d5d2ab7c",
            "sha": "d5d2ab7c467f5dfa12ffd2f598fc6937f149f115",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716109,
            "ref": "refs/orch-rescue/20260803T001509-pinned-express-lane-86901f54",
            "sha": "86901f543191cdffc57e1efe0515565fbe5d182a",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716109,
            "ref": "refs/orch-rescue/20260803T001509-prompt-evolution-bandit-8f2ca834",
            "sha": "8f2ca83412d4d141ede193baca9c6017fbadbfdb",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716629,
            "ref": "refs/orch-rescue/20260803T002350-breach-remediation-1857df97",
            "sha": "1857df97ac5e4f01d161c0b799fc410e7aeef0b2",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716631,
            "ref": "refs/orch-rescue/20260803T002351-cc-solvency-passport-5a4083d8",
            "sha": "5a4083d80552d0ae539be2d9266f4e226231fcbf",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716632,
            "ref": "refs/orch-rescue/20260803T002352-convention-conformance-lints-cef96764",
            "sha": "cef967641c16ba3f50026b808a7efa86024ccc50",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716633,
            "ref": "refs/orch-rescue/20260803T002353-economic-scheduler-revenue-5d544ba0",
            "sha": "5d544ba086972bd63eae767969e9e26ff6f9648b",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716633,
            "ref": "refs/orch-rescue/20260803T002354-hive-enforcement-velocity-index-46ca1c00",
            "sha": "46ca1c0053774b7ad3b35d80e9b3d63cc9f153f3",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716636,
            "ref": "refs/orch-rescue/20260803T002356-merged-diff-memory-a09a6ac1",
            "sha": "a09a6ac1fa4927304d4f24ec1f3824a176920e7f",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716638,
            "ref": "refs/orch-rescue/20260803T002358-orch-config-consumption-6600266e",
            "sha": "6600266e945e9a26e569d650b4135db992fc8d9b",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716641,
            "ref": "refs/orch-rescue/20260803T002401-ploeh-s2s-bridge-tomorrow-0dea12b4",
            "sha": "0dea12b460d778337c5f1606a3afbf7c6c8e5b7c",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716643,
            "ref": "refs/orch-rescue/20260803T002403-smarter-5-95-50fcf130",
            "sha": "50fcf1309d2e098989143763fafe8e7183505648",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785719716,
            "ref": "refs/orch-rescue/20260803T011516-ext-streaming-terms-832b02eb",
            "sha": "832b02ebdb516161a52be669d888bf41c0c246c8",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 224,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/Sustainable_Barks"
      }
    ]
