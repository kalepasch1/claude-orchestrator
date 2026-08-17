PROJECT: darwn

- id: chatgpt-local-reconcile-darwn-cba9a5a9cf54
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
    `cba9a5a9cf54f95f0b525aab0c28f3a5113d565a53c37f14e07e5e170dd92114`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
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
            "committed_at": 1786136363,
            "ref": "agent/canary-darwn-20260713-slice-1-adapt-existing-diff-templates",
            "sha": "fda769d43114e41518dd5a49a247ccac9f339dab",
            "subject": "recovery-intent-stub: canary-darwn-20260713-slice-1-adapt-existing-diff-templates"
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
            "committed_at": 1786593102,
            "ref": "agent/dropbox-darwn-rescue-recover-referral-standing",
            "sha": "a0893f64aced970d5b8fd81727db5357a4057523",
            "subject": "recover(referral): port referral standing materialization from rescue ref eef8506"
          },
          {
            "committed_at": 1785848773,
            "ref": "agent/qafix-darwn-07251340",
            "sha": "4200e42e95ed45a95ccef0cfb3ebd564e9af4f57",
            "subject": "recovery-intent-stub: qafix-darwn-07251340"
          },
          {
            "committed_at": 1786028483,
            "ref": "agent/recover-missing-branch-backlog-batch-darwn-5b34a9d-slice-3",
            "sha": "f4515a70c0eca68467c29ea66ea1f4962d1bd6bc",
            "subject": "recovery-intent-stub: recover-missing-branch-backlog-batch-darwn-5b34a9d-slice-3"
          },
          {
            "committed_at": 1786187110,
            "ref": "agent/remediate-diligence-page",
            "sha": "7eb541f9e8b479346f574524646587ac64715b9a",
            "subject": "recovery-intent-stub: remediate-diligence-page"
          }
        ],
        "count": 22,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      }
    ]
