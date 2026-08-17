PROJECT: darwn

- id: chatgpt-local-reconcile-darwn-570a6495a33e
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
    `570a6495a33e93f24141f5e2483df623ab1ab17876bc9f45abce68f461eeccbc`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches_digest": "707ce3b9112251353010e9910dcabb9288ae1b27a5d4494499a5bfffa0807a34",
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
            "committed_at": 1786801523,
            "ref": "agent/chatgpt-local-reconcile-darwn-f87c64c83b9f",
            "sha": "c2825c5edc33b8a3754ccc3a59c8caa24d30bedf",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-darwn-f87c64c83b9f"
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
          }
        ],
        "branches_total": 56,
        "count": 56,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      }
    ]
