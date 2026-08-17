PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-3de61f6e2ca2
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
    `3de61f6e2ca2fe2f309472d63dd342e664f3605fca36a24560bb5b54bcec0224`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
            "committed_at": 1786941338,
            "ref": "agent/chatgpt-local-reconcile-racefeed-11d5bb2af2f3",
            "sha": "23c7f50a7262fb9c3e430e9bd040684915ce9143",
            "subject": "agent: chatgpt-local-reconcile-racefeed-11d5bb2af2f3 \u2014 23/23 classified, 0 unknown; recovered v15Adapter + prior ledgers from the unpushed master tip"
          },
          {
            "committed_at": 1786943206,
            "ref": "agent/chatgpt-local-reconcile-racefeed-3f3360fbf871",
            "sha": "c04265b90782bc9041c74bc5ab6e25032ca45822",
            "subject": "agent: chatgpt-local-reconcile-racefeed-3f3360fbf871"
          },
          {
            "committed_at": 1786794221,
            "ref": "agent/chatgpt-local-reconcile-racefeed-54a71fe5564f",
            "sha": "2e47b7843182a3bb3fa0c040f34d1bd6fd747206",
            "subject": "agent: chatgpt-local-reconcile-racefeed-54a71fe5564f"
          },
          {
            "committed_at": 1786943279,
            "ref": "agent/chatgpt-local-reconcile-racefeed-5da549057d91",
            "sha": "748299fe9ec1744b6f1950930af102a3f71ffc4f",
            "subject": "agent: chatgpt-local-reconcile-racefeed-5da549057d91"
          },
          {
            "committed_at": 1786794271,
            "ref": "agent/chatgpt-local-reconcile-racefeed-6746994b1052",
            "sha": "c23fb98f8377b30b321cc4f85cf543bf73f07368",
            "subject": "agent: chatgpt-local-reconcile-racefeed-6746994b1052"
          },
          {
            "committed_at": 1786937422,
            "ref": "agent/chatgpt-local-reconcile-racefeed-7b80bbefa5f6",
            "sha": "816c9e72e628b210e864d41e32ee9a8340baeacd",
            "subject": "reconcile(recovery): classify 513 orch-rescue refs, zero UNKNOWN, nothing to recover"
          },
          {
            "committed_at": 1786805082,
            "ref": "agent/chatgpt-local-reconcile-racefeed-7df99c040014",
            "sha": "ad53edd81276634d29bd326f8f254b04bbb97d21",
            "subject": "agent: chatgpt-local-reconcile-racefeed-7df99c040014 \u2014 verified recovery ledger, 5/5 classified, 0 unknown"
          },
          {
            "committed_at": 1786834144,
            "ref": "agent/chatgpt-local-reconcile-racefeed-a253a4a6626a",
            "sha": "5d7372d7f32b315c5d71f5cadc464d8d6bf66133",
            "subject": "agent: chatgpt-local-reconcile-racefeed-a253a4a6626a"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/contracts-smarter",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-env-key-disable",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786943792,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-governor-ram-floor",
            "sha": "5df01f9907eb6218985b3b0ed5209853ea786691",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-5da549057d91' (auto-resolved)"
          },
          {
            "committed_at": 1786943792,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-single-supervisor",
            "sha": "5df01f9907eb6218985b3b0ed5209853ea786691",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-5da549057d91' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-deploy-kpi",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786943792,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-interlock-tests",
            "sha": "5df01f9907eb6218985b3b0ed5209853ea786691",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-5da549057d91' (auto-resolved)"
          },
          {
            "committed_at": 1786797438,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter",
            "sha": "b092d21c1825aaedcde482053cc0835a686e414d",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-6746994b1052' (auto-resolved)"
          },
          {
            "committed_at": 1786805439,
            "ref": "agent/orch-config-consumption",
            "sha": "fea4dc36d3c9a13d29784eb104a37dda5e5e8303",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-7df99c040014' (auto-resolved)"
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
            "committed_at": 1786943792,
            "ref": "master",
            "sha": "5df01f9907eb6218985b3b0ed5209853ea786691",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-5da549057d91' (auto-resolved)"
          },
          {
            "committed_at": 1786943792,
            "ref": "orchestrator/dev",
            "sha": "5df01f9907eb6218985b3b0ed5209853ea786691",
            "subject": "Merge branch 'agent/chatgpt-local-reconcile-racefeed-5da549057d91' (auto-resolved)"
          }
        ],
        "count": 29,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      },
      {
        "count": 185,
        "items_digest": "2c9d953b16cad642afd9898facb84424ab5d21438c3f2360f31021892270fa45",
        "items_sample": [
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-c129734ad13bbee1e964",
            "sha": "4e7e86ff6f80dad2280413f2d0d5e485aa2ba1d6",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-racefeed",
            "sha": "b4939da0fa03dd1feba5f09c793f26c7b38228c4",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715612,
            "ref": "refs/orch-rescue/20260803T000652-cade-mirror-negotiation",
            "sha": "b86ed82ed72c6377e16cb54d1ac8427f081ee0a0",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-c129734ad13bbee1e964",
            "sha": "c2e65b91806a7c29a335c2bc24f03f90391ab3c5",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715656,
            "ref": "refs/orch-rescue/20260803T000736-racefeed",
            "sha": "dcb601aae88f7e1095587b7ae3a5d0a795560567",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715662,
            "ref": "refs/orch-rescue/20260803T000742-cade-mirror-negotiation",
            "sha": "257bd307b0eb763b2d141611328c76278f2e8d92",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716109,
            "ref": "refs/orch-rescue/20260803T001509-cade-mirror-negotiation-5d6be412",
            "sha": "5d6be4128adaf8b82f5067286f58ef1db006aea3",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716621,
            "ref": "refs/orch-rescue/20260803T002341-breach-remediation-365af4d9",
            "sha": "365af4d9751662eabd36e7a47794c5cf3d1a799f",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716622,
            "ref": "refs/orch-rescue/20260803T002342-cc-legacy-margin-removal-3377f3a4",
            "sha": "3377f3a42cc6e5a1a5fba44a64d94c00a8f83684",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716622,
            "ref": "refs/orch-rescue/20260803T002342-cc-mutual-default-fund-5f676baa",
            "sha": "5f676baa307942820d261d87209381cc42de1a34",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716623,
            "ref": "refs/orch-rescue/20260803T002343-cc-solvency-passport-80b65f19",
            "sha": "80b65f191cc60feaf52d8de4af862a5f8239d60a",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716623,
            "ref": "refs/orch-rescue/20260803T002344-convention-conformance-lints-4bd19fae",
            "sha": "4bd19fae4c68d0575df91bfba211d79a779379b4",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716624,
            "ref": "refs/orch-rescue/20260803T002344-economic-scheduler-revenue-54afa63b",
            "sha": "54afa63ba6ac27d11c236629ddc9e7327ca2cc4e",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716625,
            "ref": "refs/orch-rescue/20260803T002345-hive-support-entity-relationship-source-2f98e4a0",
            "sha": "2f98e4a00455ab90a93cc4e3c536280776c69a1a",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716625,
            "ref": "refs/orch-rescue/20260803T002345-merged-diff-memory-5d03bebb",
            "sha": "5d03bebb97c272ec35387f09cd790588242b74e9",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716626,
            "ref": "refs/orch-rescue/20260803T002346-orch-config-consumption-ec8347f1",
            "sha": "ec8347f1150cc3446f14c4795ff7e0e8b957ffc9",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716626,
            "ref": "refs/orch-rescue/20260803T002346-pinned-express-lane-0aea24b7",
            "sha": "0aea24b750b8e497798f44deedb755cfec861002",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716627,
            "ref": "refs/orch-rescue/20260803T002347-ploeh-s2s-bridge-tomorrow-7dff4c8d",
            "sha": "7dff4c8dfb4edfee5d8bc81a257666f8fdded0b7",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716627,
            "ref": "refs/orch-rescue/20260803T002348-prompt-evolution-bandit-962cb543",
            "sha": "962cb543a8faad8c5f4c6cc1326d2022062c8fa9",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785716628,
            "ref": "refs/orch-rescue/20260803T002348-smarter-5-95-11b35c90",
            "sha": "11b35c902f25a67c002e9ebb92cfae0fdbd9b3f8",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717535,
            "ref": "refs/orch-rescue/20260803T003855-c129734ad13bbee1e964-run-58667-1785716864315207000-bb1a18bb",
            "sha": "bb1a18bb5e21aeea345ddd067ba2a43f93117687",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717536,
            "ref": "refs/orch-rescue/20260803T003856-c129734ad13bbee1e964-run-59519-1785717024310216000-2332ecf4",
            "sha": "2332ecf486232df45185bd7ee4bd69d51c080623",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717536,
            "ref": "refs/orch-rescue/20260803T003856-c129734ad13bbee1e964-run-59519-1785717057935029000-2332ecf4",
            "sha": "2332ecf486232df45185bd7ee4bd69d51c080623",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717548,
            "ref": "refs/orch-rescue/20260803T003908-c129734ad13bbee1e964-run-79152-1785716926103143000-abc696c8",
            "sha": "abc696c80a11b1a454c23659d5440e5640c79038",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717559,
            "ref": "refs/orch-rescue/20260803T003919-c129734ad13bbee1e964-run-94270-1785717304432121000-e37adbdd",
            "sha": "e37adbdd2360dbdcf3ddb9101c84aae75f52a9ab",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717561,
            "ref": "refs/orch-rescue/20260803T003921-c129734ad13bbee1e964-run-95658-1785716992540673000-f61f48a9",
            "sha": "f61f48a942789b17c9b53d6661d5a11257eeb186",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717834,
            "ref": "refs/orch-rescue/20260803T004354-c129734ad13bbee1e964-run-26877-1785717774228697000-d4d555be",
            "sha": "d4d555be911f504ead07b5a94986465e7cfa72f5",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717838,
            "ref": "refs/orch-rescue/20260803T004358-ext-streaming-terms-90ad7f40",
            "sha": "90ad7f405eeea48c69af6130ec2a26d234442f37",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785717839,
            "ref": "refs/orch-rescue/20260803T004359-oc-autoclear-policy-28b60428",
            "sha": "28b60428b0a975241f5740b5fa622abed207a3b9",
            "subject": "On agent/oc-autoclear-policy: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785718286,
            "ref": "refs/orch-rescue/20260803T005126-c129734ad13bbee1e964-run-43567-1785717841681926000-ef0c6b00",
            "sha": "ef0c6b0065a368f7c7c3efc3a18719b3f5db1582",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          }
        ],
        "items_total": 185,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      }
    ]
