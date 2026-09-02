PROJECT: illuminati

- id: chatgpt-local-reconcile-illuminati-3956d0f9df71
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
    `3956d0f9df71dae6dad1f31682e32ece9b923ce00276f667e4b96b811b17ffe1`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 705,
        "items_digest": "f7000ee92bc9cf1691f3ac985835389c5cf99407dbff75e416abd56c06802473",
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
            "created_at": 1785949985,
            "ref": "refs/orch-rescue/20260805T171309-illuminati-a5d467f3",
            "sha": "a5d467f335d99c399d591141177fe9988068ce6d",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785950115,
            "ref": "refs/orch-rescue/20260805T171520-illuminati-a64b20d7",
            "sha": "a64b20d777188e4068f7457c5e38160e4e85ae5d",
            "subject": "On master: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 705,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/illuminati"
      }
    ]
