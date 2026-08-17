PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-b77c125e7b6c
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
    `b77c125e7b6cb11413ab93a5e15a56c02f7e26875ea65fbfd52af8cf1295a625`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 4,
        "changes": [
          "IMPLEMENTATION_PROMPT.md",
          "Sustainable_Barks_Strategic_Analysis.docx",
          "app.vue",
          "composables/useCanonical.ts"
        ],
        "changes_digest": "8264e9fc6b5b94944095119439d38f00b6fa524206e240e9eec3c730fd7884ae",
        "head": "45810f532c7c5b4c912d7310b415a90456d00406",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1784986420,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/merge-legacy-agent-funding-equilibrium"
      },
      {
        "branches": [
          {
            "committed_at": 1785677351,
            "ref": "agent/backlog-batch-sustainable-barks-d4feb77-slice-4",
            "sha": "1bc845fc6fff85f2f2fb98b25a9f0426d4b9b5a9",
            "subject": "docs: audit 35 legacy agent branches \u2014 25 merged, 10 unmerged with disposition"
          },
          {
            "committed_at": 1786141273,
            "ref": "agent/backlog-batch-sustainable-barks-d4feb77-slice-4-fix-failure",
            "sha": "7f00c9acd01556f4106766c52f8fae404e678ac2",
            "subject": "recovery-intent-stub: backlog-batch-sustainable-barks-d4feb77-slice-4-fix-failure"
          },
          {
            "committed_at": 1785677754,
            "ref": "agent/backlog-batch-sustainable-barks-d4feb77-slice-5",
            "sha": "aefce39ecc36decf9cd296a3ee6282227bf9b16b",
            "subject": "agent: backlog-batch-sustainable-barks-d4feb77-slice-5"
          },
          {
            "committed_at": 1785677556,
            "ref": "agent/canary-sustainable-barks-20260708-analyze-beethoven-branch-recovery-patch",
            "sha": "2cefd2c1858ddba5d4dddb7e827bb45c5f8a1f89",
            "subject": "docs: analyze beethoven branch recovery \u2014 25 merged, 11 unmerged, recovery plan"
          },
          {
            "committed_at": 1786060418,
            "ref": "agent/canary-sustainable-barks-20260708-analyze-beethoven-branch-recovery-patch-analyz",
            "sha": "18b2499568cd20dd74a1614613a9903c5f3183d3",
            "subject": "salvage: interrupted work for canary-sustainable-barks-20260708-analyze-beethoven-branch-recovery-patch-analyz"
          },
          {
            "committed_at": 1785677677,
            "ref": "agent/canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch",
            "sha": "e04d4ea7cbe57afc5eb1d11a0b8f6d800d199603",
            "subject": "agent: canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch"
          },
          {
            "committed_at": 1786060455,
            "ref": "agent/canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-apply-be",
            "sha": "093d48984b20602d7c32c1d3e844b7e07f674a18",
            "subject": "salvage: interrupted work for canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-apply-be"
          },
          {
            "committed_at": 1786136060,
            "ref": "agent/canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-inspect-",
            "sha": "6156d9e8bcf81bbc130ef412027031b6676640ae",
            "subject": "recovery-intent-stub: canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-inspect-"
          },
          {
            "committed_at": 1786060474,
            "ref": "agent/canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-test-and",
            "sha": "260852bf05d32cf161bef46d2a85b2f61b010855",
            "subject": "salvage: interrupted work for canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-test-and"
          },
          {
            "committed_at": 1786021116,
            "ref": "agent/canary-sustainable-barks-20260708-final-system-validation-final-validation-and-d",
            "sha": "11a40c44be6dd9d825b4093b38c7d4d6d1c15092",
            "subject": "regen-from-cache(template): canary-sustainable-barks-20260708-final-system-validation-final-validation-and-d"
          },
          {
            "committed_at": 1785749655,
            "ref": "agent/canary-sustainable-barks-20260708-final-system-validation-run-integration-and-e2",
            "sha": "970aad6caa50ea593e414fd88f5b7ce32a79937e",
            "subject": "salvage: interrupted work for canary-sustainable-barks-20260708-final-system-validation-run-integration-and-e2"
          },
          {
            "committed_at": 1786150996,
            "ref": "agent/canary-sustainable-barks-20260708-final-system-validation-run-pricinggridreconst",
            "sha": "3b4641e092bcf3b639c18f70f63caef9fec2e863",
            "subject": "recovery-intent-stub: canary-sustainable-barks-20260708-final-system-validation-run-pricinggridreconst"
          },
          {
            "committed_at": 1786020901,
            "ref": "agent/canary-sustainable-barks-20260708-final-system-validation-run-unit-tests",
            "sha": "26b155e5ca6588e1e5efdce61a4733e9d582ea2a",
            "subject": "regen-from-cache(template): canary-sustainable-barks-20260708-final-system-validation-run-unit-tests"
          },
          {
            "committed_at": 1786020578,
            "ref": "agent/canary-sustainable-barks-20260708-final-system-validation-validate-pricinggrid-d",
            "sha": "0aef68a19f5b73a967cd70397c38361dc3311af9",
            "subject": "regen-from-cache(template): canary-sustainable-barks-20260708-final-system-validation-validate-pricinggrid-d"
          },
          {
            "committed_at": 1786150941,
            "ref": "agent/canary-sustainable-barks-20260708-final-system-validation-verify-adaptations",
            "sha": "57310c9fcccb0935b04424451902351624e8fd8d",
            "subject": "recovery-intent-stub: canary-sustainable-barks-20260708-final-system-validation-verify-adaptations"
          },
          {
            "committed_at": 1786151245,
            "ref": "agent/canary-sustainable-barks-20260708-final-system-validation-verify-library-adaptat",
            "sha": "2aaf9d3d6e1d0342aa6dc40b51e3a354861c73c5",
            "subject": "recovery-intent-stub: canary-sustainable-barks-20260708-final-system-validation-verify-library-adaptat"
          },
          {
            "committed_at": 1785997437,
            "ref": "agent/factory-unblock-relfix-sustainable-barks-75b39426be69",
            "sha": "73bbcc686e345e84d02ecf04a3fcb2e3377de083",
            "subject": "recovery-intent-stub: factory-unblock-relfix-sustainable-barks-75b39426be69"
          },
          {
            "committed_at": 1785682786,
            "ref": "agent/relfix-sustainable-barks-07252015",
            "sha": "754778cf0c9456a409c42d5ffdc282923c0cfebc",
            "subject": "agent: relfix-sustainable-barks-07252015"
          },
          {
            "committed_at": 1785682833,
            "ref": "agent/relfix-sustainable-barks-07252220",
            "sha": "984fef907f8cc0e6f9bb4f722845d7afdf2279d0",
            "subject": "agent: relfix-sustainable-barks-07252220"
          },
          {
            "committed_at": 1785682786,
            "ref": "agent/relfix-sustainable-barks-08011711",
            "sha": "754778cf0c9456a409c42d5ffdc282923c0cfebc",
            "subject": "agent: relfix-sustainable-barks-07252015"
          },
          {
            "committed_at": 1785972853,
            "ref": "agent/relfix-sustainable-barks-75b39426be69-rank-diff-candidates",
            "sha": "1e4480a3bfe694949213bf4b935fa6f65394a3fa",
            "subject": "agent: relfix-sustainable-barks-75b39426be69-rank-diff-candidates"
          },
          {
            "committed_at": 1786119178,
            "ref": "agent/remediate-relfix-sustainable-barks-75b39426be69-add-pricing-grid-regression-test",
            "sha": "b1e2b3fa4a36b18b0d29d6c4abb10b5e65bd07c2",
            "subject": "recovery-intent-stub: remediate-relfix-sustainable-barks-75b39426be69-add-pricing-grid-regression-test"
          },
          {
            "committed_at": 1785678567,
            "ref": "agent/shadow-2b186784-cowork",
            "sha": "4971ab16b96fa1e5dcaf444ca25d331a08384466",
            "subject": "recovery-intent-stub: shadow-2b186784-cowork"
          },
          {
            "committed_at": 1785679589,
            "ref": "agent/shadow-2b186784-orchestrator_native",
            "sha": "2f88a8b8d944b90c066ba2887e140829a526e313",
            "subject": "recovery-intent-stub: shadow-2b186784-orchestrator_native"
          },
          {
            "committed_at": 1786137631,
            "ref": "agent/weekly-lint-sustainable-barks",
            "sha": "086a1e9ac60b243a233f45d340b8fa16e511d015",
            "subject": "recovery-intent-stub: weekly-lint-sustainable-barks"
          }
        ],
        "count": 25,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/Sustainable_Barks"
      },
      {
        "count": 196,
        "items_digest": "2a2fbd1e9e46009464d3a760cb6d8ca368fc9119ac0bf701f2397b9a1260f460",
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
            "ref": "refs/orch-rescue/20260803T001509-Sustainable_Barks-2d4ec498",
            "sha": "2d4ec49823ab8b6c0d7790d6a706023b1965fc5a",
            "subject": "On main: orch-rescue: periodic sweep"
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
          }
        ],
        "items_total": 196,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/Sustainable_Barks"
      },
      {
        "count": 5,
        "items": [
          {
            "created_at": 1785429738,
            "ref": "stash@{0}",
            "sha": "8a9cd1c2bc65428f6a800326c4072f5f1b126265",
            "subject": "WIP on orchestrator/dev: a82b6ff Merge agent/funding-equilibrium: cleanup obsolete composables, middleware, config artifacts"
          },
          {
            "created_at": 1784986273,
            "ref": "stash@{1}",
            "sha": "a8f8ba184283aa9ef89485646c2952ba452f365c",
            "subject": "WIP on main: 45810f5 fix: regenerate package-lock.json in sync with package.json"
          },
          {
            "created_at": 1784427673,
            "ref": "stash@{2}",
            "sha": "31b76a46c89a5f182a496515fd504ff7260de175",
            "subject": "WIP on agent/recover-missing-branch-canary-sustainable-barks-20260708-slice-1: 6285c9a agent: recover-missing-branch-canary-sustainable-barks-20260708-slice-1 \u2014 add rate-limit memory guard and test helper"
          },
          {
            "created_at": 1784427537,
            "ref": "stash@{3}",
            "sha": "d87a1cb4de8aef4da609df839d33644aeaafc6ba",
            "subject": "WIP on agent/recover-missing-branch-canary-sustainable-barks-20260708-slice-1: 6285c9a agent: recover-missing-branch-canary-sustainable-barks-20260708-slice-1 \u2014 add rate-limit memory guard and test helper"
          },
          {
            "created_at": 1783973183,
            "ref": "stash@{4}",
            "sha": "43bc336bf6008b94ae5add891018543cf8b02045",
            "subject": "WIP on main: f71e3db agent/bx2: canary-sustainable-barks-20260709 heartbeat"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/Sustainable_Barks"
      }
    ]
