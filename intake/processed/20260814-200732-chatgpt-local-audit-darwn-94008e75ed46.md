PROJECT: darwn

- id: chatgpt-local-reconcile-darwn-94008e75ed46
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
    `94008e75ed468fb4f289a91045db3b92d591ae4b45173522dddb20ef007dadd8`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches_digest": "3be7f91fb984737e414d9b12b38d266625eb6ce7429fdd1e90d6890e1938c6e9",
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
            "committed_at": 1786654063,
            "ref": "agent/chatgpt-local-reconcile-darwn-87db0cc80434",
            "sha": "329c2c6a1de38b3ef70206a05f3aa2a99a62f3ff",
            "subject": "agent: chatgpt-local-reconcile-darwn-87db0cc80434"
          },
          {
            "committed_at": 1786654034,
            "ref": "agent/chatgpt-local-reconcile-darwn-cba9a5a9cf54",
            "sha": "1acecb066766355928be0f19f4610afae1c236ed",
            "subject": "agent: chatgpt-local-reconcile-darwn-cba9a5a9cf54"
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
          },
          {
            "committed_at": 1786670240,
            "ref": "agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1-clean-670239",
            "sha": "88ce4ac98df8dbdbcbddc86837a5988f33ceff48",
            "subject": "self-heal: clean files from agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1 (14 files)"
          },
          {
            "committed_at": 1786672971,
            "ref": "agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1-clean-672970",
            "sha": "99d8e2e20478b94456cb03c49791f12ecf45c491",
            "subject": "self-heal: clean files from agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1 (14 files)"
          },
          {
            "committed_at": 1786674370,
            "ref": "agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1-clean-674369",
            "sha": "641a27f88ac400ae3f467f8d6fc85f2bf7eced51",
            "subject": "self-heal: clean files from agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1 (14 files)"
          },
          {
            "committed_at": 1786674395,
            "ref": "agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1-clean-674394",
            "sha": "f53ab1f63d8756209f674bf47ee2c2a1ad3a7b05",
            "subject": "self-heal: clean files from agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1 (14 files)"
          },
          {
            "committed_at": 1786676102,
            "ref": "agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1-clean-676101",
            "sha": "0ec6fa8a0226ae10f89eee240f95d60fea64db3f",
            "subject": "self-heal: clean files from agent/dropbox-darwn-rescue-recover-ref-bef9208-slice-1 (14 files)"
          }
        ],
        "branches_total": 41,
        "count": 41,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      },
      {
        "branch": "main",
        "change_count": 2,
        "changes": [
          "package-lock.json",
          "package.json"
        ],
        "changes_digest": "8eb04b752d06e240df3b079938a3146c7955a13a45e5f3aede8ee17505b85c23",
        "head": "1643c0afbca3b16bb8427fbbf9886de0767f9775",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1784930411,
        "path": "/Users/kpasch/Documents/darwinLife"
      }
    ]
