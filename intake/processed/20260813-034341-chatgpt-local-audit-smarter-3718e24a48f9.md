PROJECT: smarter

- id: chatgpt-local-reconcile-smarter-3718e24a48f9
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
    `3718e24a48f9a23e69624462644e77d2831e349121be5ed9823413c4bca30330`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
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
            "committed_at": 1786119702,
            "ref": "agent/qafix-smarter-9c3a08b5d8dd-fix-error-handling-test-typescript-error-diff-model-a",
            "sha": "6647e553146be7ba97b81186a205fc83fac9b070",
            "subject": "regen-from-cache(template): qafix-smarter-9c3a08b5d8dd-fix-error-handling-test-typescript-error-diff-model-a"
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
            "committed_at": 1784884271,
            "ref": "agent/qafix-smarter-9c3a08b5d8dd-fix-type-errors",
            "sha": "d01a553ea31e14f27fa2f7e34a06d3a6b90315fd",
            "subject": "agent: qafix-smarter-9c3a08b5d8dd-fix-type-errors"
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
            "committed_at": 1786052738,
            "ref": "agent/smarter-5-95",
            "sha": "89f761708563852afb42f9da9f817a99542a0d50",
            "subject": "feat(lint): update decision-budget enforcement with matter-detail and advanced disclosure"
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
            "committed_at": 1785957443,
            "ref": "fix-local/smarter-slice-3",
            "sha": "dfa02ec7e42beee861e328aed4fcf35b3477086d",
            "subject": "agent: dropbox-smarter-embeddable-core-apparently-pareto--slice-3"
          },
          {
            "committed_at": 1785217226,
            "ref": "review/agent-access",
            "sha": "c53b7fff64915f6519aaee40b3b377bfe62006c1",
            "subject": "test: lock in the review-access safety properties"
          }
        ],
        "count": 18,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/smarter"
      }
    ]
