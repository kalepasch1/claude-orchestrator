PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-f2fbd20b67d1
  title: Reconcile local ChatGPT/Codex build evidence for racefeed
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
    `f2fbd20b67d1d90a3a48ac498695c573dae8c363ae31d4745c20d06761727c60`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786572137,
            "ref": "agent/chatgpt-local-reconcile-racefeed-ebda4da4e0f1",
            "sha": "979170b2a90596d368ddf9b02a7f206690f9627d",
            "subject": "agent: chatgpt-local-reconcile-racefeed-ebda4da4e0f1"
          },
          {
            "committed_at": 1786136527,
            "ref": "agent/qafix-racefeed-07180346-fix-downstream-agentledger-test",
            "sha": "d694b92cb21279d52c511fe0f35487b5fe72aded",
            "subject": "recovery-intent-stub: qafix-racefeed-07180346-fix-downstream-agentledger-test"
          },
          {
            "committed_at": 1786143665,
            "ref": "agent/qafix-racefeed-07180346-verify-full-qa-gate",
            "sha": "b4e677dc2b382234a40daae681dcdbee95e54f20",
            "subject": "recovery-intent-stub: qafix-racefeed-07180346-verify-full-qa-gate"
          },
          {
            "committed_at": 1786122891,
            "ref": "agent/qafix-racefeed-5a072f924ba3",
            "sha": "870c2daf5eb685d9ce7e5ba1c354c50eb5da2d06",
            "subject": "regen-from-cache(template): qafix-racefeed-5a072f924ba3"
          },
          {
            "committed_at": 1786130133,
            "ref": "agent/qafix-racefeed-65f785fa31a3-add-regression-test-and-commit",
            "sha": "273e905f4bbdf47bb44059e55c31429f11353b47",
            "subject": "regen-from-cache(template): qafix-racefeed-65f785fa31a3-add-regression-test-and-commit"
          },
          {
            "committed_at": 1786128347,
            "ref": "agent/qafix-racefeed-65f785fa31a3-reproduce-racefeed-race-condition",
            "sha": "804f2b01480c6d9d9b64de4bf0dea822a8371e43",
            "subject": "regen-from-cache(template): qafix-racefeed-65f785fa31a3-reproduce-racefeed-race-condition"
          },
          {
            "committed_at": 1786119940,
            "ref": "agent/qafix-racefeed-daefef96359a",
            "sha": "40bc9b29dd5c41efaf9e92008354b0976b951931",
            "subject": "regen-from-cache(template): qafix-racefeed-daefef96359a"
          },
          {
            "committed_at": 1786137110,
            "ref": "agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2",
            "sha": "f1ec21396e936e86f835ebd836620682e3d46f58",
            "subject": "recovery-intent-stub: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2"
          },
          {
            "committed_at": 1786135714,
            "ref": "agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-3",
            "sha": "c87aeef8993e2ec4b8846ccf9b9fcbe8da15c351",
            "subject": "recovery-intent-stub: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-3"
          },
          {
            "committed_at": 1786140327,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-ident",
            "sha": "3bfc287a1a67371683959d0058dadbb271e5b013",
            "subject": "recovery-intent-stub: relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-ident"
          },
          {
            "committed_at": 1786140574,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-inves",
            "sha": "648dfe40c87ee6fe5103df077dca32171f3d6341",
            "subject": "recovery-intent-stub: relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-failure-inves"
          },
          {
            "committed_at": 1785861561,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-source-config",
            "sha": "f0a41d3a6dd8bdd73f91456339d136ce14097d63",
            "subject": "agent: relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-source-config \u2014 commonBrain.test runnable under node --test (.ts import, node:test+assert expect shim); fetch-nodeshim -> local stub; npm test 84/84, tsc clean"
          },
          {
            "committed_at": 1786159356,
            "ref": "agent/remediate-noop-relfix-racefeed-07060650-sub-task-3-slice-1",
            "sha": "4d104abfa394dc90ec37c425e4857b78e3256de4",
            "subject": "regen-from-cache(template): remediate-noop-relfix-racefeed-07060650-sub-task-3-slice-1"
          },
          {
            "committed_at": 1786151467,
            "ref": "agent/remediate-relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-fai",
            "sha": "918061a14892f6c7a309374d2d265025b742ab27",
            "subject": "regen-from-cache(merged_diff): remediate-relfix-racefeed-07060650-fix-typescript-and-build--slice-3-inspect-fai"
          },
          {
            "committed_at": 1786140469,
            "ref": "agent/rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c-test-and-ver",
            "sha": "370a4505c6136772aed528d0264dfd8af98a5cae",
            "subject": "recovery-intent-stub: rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c-test-and-ver"
          },
          {
            "committed_at": 1786135055,
            "ref": "agent/rework-noop-relfix-racefeed-07060650-sub-task-3-commit-package-files-if-c9074df-",
            "sha": "6cd446693764dc26808329c7205c919622d16b4f",
            "subject": "regen-from-cache(template): rework-noop-relfix-racefeed-07060650-sub-task-3-commit-package-files-if-c9074df-"
          },
          {
            "committed_at": 1786134923,
            "ref": "agent/toolchain-repair-6096aa2b-fix-node-modules-install-slice-2",
            "sha": "1bff9f559f48a1129617b2bbd815a1c10f9d8310",
            "subject": "recovery-intent-stub: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2"
          },
          {
            "committed_at": 1786135714,
            "ref": "agent/toolchain-repair-6096aa2b-fix-node-modules-install-slice-3",
            "sha": "c87aeef8993e2ec4b8846ccf9b9fcbe8da15c351",
            "subject": "recovery-intent-stub: recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-3"
          }
        ],
        "count": 18,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      }
    ]
