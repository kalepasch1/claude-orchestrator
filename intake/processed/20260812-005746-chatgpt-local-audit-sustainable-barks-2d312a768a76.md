PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-2d312a768a76
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
    `2d312a768a76b0da18392bb211ad5932c73468aea6f39f14ecc40c3101baa593`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
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
      }
    ]
