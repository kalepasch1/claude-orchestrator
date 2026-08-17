PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-7b80bbefa5f6
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
    `7b80bbefa5f67c548da44e55421c37a836f2be1066ed91549f1bfae6c4bb5103`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786797438,
            "ref": "agent/cade-mirror-negotiation",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786794221,
            "ref": "agent/chatgpt-local-reconcile-racefeed-54a71fe5564f",
            "sha": "2e47b7843182a3bb3fa0c040f34d1bd6fd747206",
            "subject": "agent: chatgpt-local-reconcile-racefeed-54a71fe5564f"
          },
          {
            "committed_at": 1786794271,
            "ref": "agent/chatgpt-local-reconcile-racefeed-6746994b1052",
            "sha": "c23fb98f8377b30b321cc4f85cf543bf73f07368",
            "subject": "agent: chatgpt-local-reconcile-racefeed-6746994b1052"
          },
          {
            "committed_at": 1786805082,
            "ref": "agent/chatgpt-local-reconcile-racefeed-7df99c040014",
            "sha": "ad53edd81276634d29bd326f8f254b04bbb97d21",
            "subject": "agent: chatgpt-local-reconcile-racefeed-7df99c040014 \u2014 verified recovery ledger, 5/5 classified, 0 unknown"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/contracts-smarter",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786805439,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause",
            "sha": "fea4dc36d3c9a13d29784eb104a37dda5e5e8303",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-7df99c040014' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-single-supervisor",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/orch-cross-project-depends",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/prompt-evolution-bandit",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1785861561,
            "ref": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-source-config",
            "sha": "f0a41d3a6dd8bdd73f91456339d136ce14097d63",
            "subject": "agent: relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-source-config \u2014 commonBrain.test runnable under node --test (.ts import, node:test+assert expect shim); fetch-nodeshim -> local stub; npm test 84/84, tsc clean"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/rework-buildfail-qafix-pareto-2080-07062319-slice-4-a7288db",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/rework-noop-relfix-racefeed-07060650-install-fetch-nodeshim-f3f967c",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/rework-oversized-relfix-racefeed-07060650-sub-task-4-report-failure-if-n-5cfe75f",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/session-proof-of-work",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/smarter-5-95",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786805439,
            "ref": "master",
            "sha": "fea4dc36d3c9a13d29784eb104a37dda5e5e8303",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-7df99c040014' (auto-resolved)"
          }
        ],
        "count": 22,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      }
    ]
