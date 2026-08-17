PROJECT: darwn

- id: chatgpt-local-reconcile-darwn-fa29d8a1d843
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
    `fa29d8a1d84311a9371da600e44eb9a77610c2a1c18730de050c3befc0633270`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/smarter-5-95",
        "change_count": 86,
        "changes_digest": "b4b57b370daefca89a47aa7fb051e02084009109c4e3728caf70ce6f09edb755",
        "changes_sample": [
          ".deploy-canary",
          ".recovery-intent-canary-darwn-20260726-define-emit-task-log-function-extract-emit-task-log-adapt-.txt",
          ".recovery-intent-canary-darwn-20260726-define-emit-task-log-function-insert-definition-in-runner-.txt",
          ".recovery-intent-canary-darwn-20260726-define-emit-task-log-function-test-no-nameerror-apply-fix-.txt",
          ".recovery-intent-canary-darwn-20260728.txt",
          ".recovery-intent-cont-677b26.txt",
          ".recovery-intent-cont-8991f1.txt",
          ".recovery-intent-cont-8fc2ce.txt",
          ".recovery-intent-improve-common-brain-evolutionary-learning-platform.txt",
          ".recovery-intent-qafix-darwn-07241816.txt",
          ".recovery-intent-qafix-darwn-07271521.txt",
          ".remediation-integration-test/remediation_5ce10748.md",
          "Adaptive-Life-Game-Design-Doc.md",
          "BACKLOG-BATCH-7CE8BFB.md",
          "CREDIT_SYSTEM.md",
          "app.vue",
          "archive/pages-backup-20260124/[...slug].vue",
          "archive/pages-backup-20260124/discover.vue",
          "archive/pages-backup-20260124/employer.vue",
          "archive/pages-backup-20260124/employer/anti-poaching.vue",
          "archive/pages-backup-20260124/employer/billing.vue",
          "archive/pages-backup-20260124/employer/dashboard.vue",
          "archive/pages-backup-20260124/employer/data-policy.vue",
          "archive/pages-backup-20260124/employer/index.vue",
          "archive/pages-backup-20260124/employer/login.vue",
          "archive/pages-backup-20260124/employer/packages.vue",
          "archive/pages-backup-20260124/employer/placement-fees.vue",
          "archive/pages-backup-20260124/employer/signup.vue",
          "archive/pages-backup-20260124/employer/terms.vue",
          "archive/pages-backup-20260124/employerSubmit.vue"
        ],
        "changes_total": 86,
        "head": "275a9519b31c455528ce0d9ef6b3305e9bd32758",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786831476,
        "path": "/Users/kpasch/Documents/darwn/darwn-wt/smarter-5-95"
      },
      {
        "branches_digest": "90dd4237c4fda11b26bddf92e31e7b6fa62c35143ef2ae9e8c026bb721833297",
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
            "committed_at": 1786815128,
            "ref": "agent/chatgpt-local-reconcile-darwn-09c949ead2e4",
            "sha": "7233b12be37e1f93044f8d4bc4c1f4772371d2b7",
            "subject": "agent: chatgpt-local-reconcile-darwn-09c949ead2e4"
          },
          {
            "committed_at": 1786830077,
            "ref": "agent/chatgpt-local-reconcile-darwn-570a6495a33e",
            "sha": "38b2b31997730ee813ff8fc6ed5d438e957f6f45",
            "subject": "agent: chatgpt-local-reconcile-darwn-570a6495a33e"
          },
          {
            "committed_at": 1786654063,
            "ref": "agent/chatgpt-local-reconcile-darwn-87db0cc80434",
            "sha": "329c2c6a1de38b3ef70206a05f3aa2a99a62f3ff",
            "subject": "agent: chatgpt-local-reconcile-darwn-87db0cc80434"
          },
          {
            "committed_at": 1786824733,
            "ref": "agent/chatgpt-local-reconcile-darwn-87dc3d8b43ff",
            "sha": "b98b69453fdb2e853f425ececd63f159f3000c72",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-darwn-87dc3d8b43ff"
          },
          {
            "committed_at": 1786820241,
            "ref": "agent/chatgpt-local-reconcile-darwn-94008e75ed46",
            "sha": "d99f555a306e9188189ec549cc7de8feea119b04",
            "subject": "agent: chatgpt-local-reconcile-darwn-94008e75ed46"
          },
          {
            "committed_at": 1786821128,
            "ref": "agent/chatgpt-local-reconcile-darwn-96fdba51ed7e",
            "sha": "693b652aaf9b54f6f41120e84369d92eeb1e6bbc",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-darwn-96fdba51ed7e"
          },
          {
            "committed_at": 1786794337,
            "ref": "agent/chatgpt-local-reconcile-darwn-99b3c3bd9840",
            "sha": "2b7d6173f0673f81ce9a726540f2569bf1bb809c",
            "subject": "agent: chatgpt-local-reconcile-darwn-99b3c3bd9840"
          },
          {
            "committed_at": 1786820720,
            "ref": "agent/chatgpt-local-reconcile-darwn-a116d884bcce",
            "sha": "862be6c585ed21ebd799d0b2c1c98e3d5dff4a8e",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-darwn-a116d884bcce"
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
            "committed_at": 1786817597,
            "ref": "agent/chatgpt-local-reconcile-darwn-fdef23f9fa9a",
            "sha": "0d71df6738318924df2b18530b71b9bb01d0d51a",
            "subject": "agent: chatgpt-local-reconcile-darwn-fdef23f9fa9a"
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
          }
        ],
        "branches_total": 65,
        "count": 65,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      }
    ]
