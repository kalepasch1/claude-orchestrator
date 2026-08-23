PROJECT: darwn

- id: chatgpt-local-reconcile-darwn-03fa345ffecd
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
    `03fa345ffecd920144bcf774ee28c1dd4753058cd0fc28e06f9cb0d2325dba93`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
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
      },
      {
        "branches_digest": "c4040f2ae4a271aa1b56b22347bfd1c870ac419c67f8e2a849c375abcc5c6337",
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
            "committed_at": 1786940441,
            "ref": "agent/chatgpt-local-reconcile-darwn-09c949ead2e4",
            "sha": "28d26461d2341ad0554bbbd43ee12bad78cc6016",
            "subject": "agent: chatgpt-local-reconcile-darwn-09c949ead2e4"
          },
          {
            "committed_at": 1786940415,
            "ref": "agent/chatgpt-local-reconcile-darwn-1fc54b298303",
            "sha": "52c002312849b866c7e1ebf514d323ed93015025",
            "subject": "agent: chatgpt-local-reconcile-darwn-1fc54b298303 \u2014 62/62 evidence items classified, 0 unknown; recovered calibration + zkPrivilegeProof + remediation test-isolation (60/60 tests green)"
          },
          {
            "committed_at": 1786938482,
            "ref": "agent/chatgpt-local-reconcile-darwn-203a4f148c75",
            "sha": "8e0da449c11a78fa97dd3d54f4778a7c4fd3f0a3",
            "subject": "reconcile(recovery): classify 231 orch-rescue refs; the one genuine loss is queued, not replayed"
          },
          {
            "committed_at": 1786940405,
            "ref": "agent/chatgpt-local-reconcile-darwn-50f61de9fbef",
            "sha": "e650e2e6dc2b0d3f8ab266c55e6554bf2db70263",
            "subject": "agent: chatgpt-local-reconcile-darwn-50f61de9fbef"
          },
          {
            "committed_at": 1786830077,
            "ref": "agent/chatgpt-local-reconcile-darwn-570a6495a33e",
            "sha": "38b2b31997730ee813ff8fc6ed5d438e957f6f45",
            "subject": "agent: chatgpt-local-reconcile-darwn-570a6495a33e"
          },
          {
            "committed_at": 1786938488,
            "ref": "agent/chatgpt-local-reconcile-darwn-794633f2a1d0",
            "sha": "a5667f2a82e71c1220a1e0fbe73b1f9759184df7",
            "subject": "reconcile(recovery): classify 231 orch-rescue refs; the one genuine loss is queued, not replayed"
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
            "committed_at": 1786938465,
            "ref": "agent/chatgpt-local-reconcile-darwn-925feacf493f",
            "sha": "0700e5872ebac0f17912cbd5c754931e4bf6d02a",
            "subject": "reconcile(recovery): classify 231 orch-rescue refs; queue the one genuine loss"
          },
          {
            "committed_at": 1786820241,
            "ref": "agent/chatgpt-local-reconcile-darwn-94008e75ed46",
            "sha": "d99f555a306e9188189ec549cc7de8feea119b04",
            "subject": "agent: chatgpt-local-reconcile-darwn-94008e75ed46"
          },
          {
            "committed_at": 1786938475,
            "ref": "agent/chatgpt-local-reconcile-darwn-94ac20224be1",
            "sha": "26fb91955fa96aa079fa2e98c0aaca36bbf2e544",
            "subject": "reconcile(recovery): classify 231 orch-rescue refs; the one genuine loss is queued, not replayed"
          },
          {
            "committed_at": 1786821128,
            "ref": "agent/chatgpt-local-reconcile-darwn-96fdba51ed7e",
            "sha": "693b652aaf9b54f6f41120e84369d92eeb1e6bbc",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-darwn-96fdba51ed7e"
          },
          {
            "committed_at": 1786939411,
            "ref": "agent/chatgpt-local-reconcile-darwn-99b3c3bd9840",
            "sha": "81690129b18d37bb2d04576d20bbd1c4afcb1acb",
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
            "committed_at": 1786939407,
            "ref": "agent/chatgpt-local-reconcile-darwn-d11e8740c03a",
            "sha": "8f36dcd12f7a733fa39145823df217a36ceaf5f7",
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
          }
        ],
        "branches_total": 74,
        "count": 74,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      },
      {
        "count": 9,
        "items": [
          {
            "created_at": 1786999128,
            "ref": "stash@{0}",
            "sha": "5b5d02fe587139a86fdc3805b03fa2a25bc734d8",
            "subject": "WIP on main: bf1b547 [remediation] Add placeholder for no-op scope: test-agent-scope"
          },
          {
            "created_at": 1785439584,
            "ref": "stash@{1}",
            "sha": "964d888c9fb246d38d82ef74c90838450d152a49",
            "subject": "WIP on agent/backlog-batch-darwn-5b34a9d-slice-4: 6d0fc45 fix: resolve tilde alias in vitest configuration"
          },
          {
            "created_at": 1784926316,
            "ref": "stash@{2}",
            "sha": "e8b5bc7c64f66b23098b8e7c2c99e6767fdc1fae",
            "subject": "WIP on main: 6d0fc45 fix: resolve tilde alias in vitest configuration"
          },
          {
            "created_at": 1784757675,
            "ref": "stash@{3}",
            "sha": "149e9b81987ce696dcefddceeade3d0802d60dbf",
            "subject": "autostash"
          },
          {
            "created_at": 1784686648,
            "ref": "stash@{4}",
            "sha": "9a147daa95c6aee5cb75ac607d08de75b085153f",
            "subject": "WIP on agent/cade-roster-seed-fin: 8e551fc agent/bx2: canary-darwn-20260709 heartbeat"
          },
          {
            "created_at": 1784229220,
            "ref": "stash@{5}",
            "sha": "5df14d7917f03dcdc67e45aa5cac36228ec9bd46",
            "subject": "WIP on recovery/concurrent-primary-20260715-darwn: 785682b recovery: preserve late dormant-source transition"
          },
          {
            "created_at": 1783831777,
            "ref": "stash@{6}",
            "sha": "d8c40ccbb593526244f37aeefa9cbb904e66c6d4",
            "subject": "On agent/reroute-model-keys-mock: wip-before-task-branches"
          },
          {
            "created_at": 1783310605,
            "ref": "stash@{7}",
            "sha": "06c9d22287de0b4ef2198a284b9427c16d6c58c2",
            "subject": "On medicalOnly: recover_and_ship: pre-merge dirt 1783310605"
          },
          {
            "created_at": 1774451483,
            "ref": "stash@{8}",
            "sha": "e63e085bdc8677a8705cbbdaa4818a02706e3fd1",
            "subject": "WIP on main: fc2cd9d adding user home page (working)"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/darwn/darwn"
      },
      {
        "kind": "unregistered_local_repo",
        "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
        "path": "/Users/kpasch/Documents/darwinLife",
        "routing": "darwn"
      }
    ]
