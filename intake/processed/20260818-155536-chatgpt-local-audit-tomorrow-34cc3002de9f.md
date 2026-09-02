PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-34cc3002de9f
  title: Reconcile local ChatGPT/Codex build evidence for tomorrow
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
    `34cc3002de9f1126048b7de083fdd9b36b988f914d0a6d5f58b3e2165cd9e320`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches_digest": "5e3d47ddf562cd7507b31f6db4271b2b3f3c11a8d85037c5eb1f717aafdf91f8",
        "branches_sample": [
          {
            "committed_at": 1786013209,
            "ref": "agent/backlog-batch-tomorrow-2250a1e-adapt-prior-diffs-generate-diff-patch",
            "sha": "5348437bc02c6cd27a174dd7d38511f7c52d7b9f",
            "subject": "agent: backlog-batch-tomorrow-2250a1e-adapt-prior-diffs-generate-diff-patch"
          },
          {
            "committed_at": 1786590381,
            "ref": "agent/bugfix-curation-institution-taxonomy-conflict",
            "sha": "daacf102739e477d05e4f882731908a2507b30c8",
            "subject": "agent: bugfix-curation-institution-taxonomy-conflict"
          },
          {
            "committed_at": 1787046743,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-1f47cd19090f",
            "sha": "511abb3c5ff906604e0925414465c9f49a02475e",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-1f47cd19090f"
          },
          {
            "committed_at": 1787041014,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-8dc004d4fd76",
            "sha": "65b78b9640e665dd60abd625fa862201e1877269",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-8dc004d4fd76"
          },
          {
            "committed_at": 1787028070,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-951f1b7c8e7e",
            "sha": "afe0b10d116acbcd11a8d42667db0c5d211a7afa",
            "subject": "merge: agent/chatgpt-local-reconcile-tomorrow-75872331e5cf"
          },
          {
            "committed_at": 1786803084,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-b8f5cf32cb21",
            "sha": "8727d9eae6100e04a85866dd46e3e0089805eb4c",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-b8f5cf32cb21"
          },
          {
            "committed_at": 1786610262,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-c875b5d08a36",
            "sha": "b1bdef04532a1e1b7bbbe6e26ed0ce28766c59b9",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-c875b5d08a36"
          },
          {
            "committed_at": 1786799232,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-d1fe07cc7ffa",
            "sha": "9d5f2dcfdd611f2c33397223f68c954ccdcbc1b1",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-d1fe07cc7ffa"
          },
          {
            "committed_at": 1787028070,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-e4df125e5dfe-slice-2",
            "sha": "afe0b10d116acbcd11a8d42667db0c5d211a7afa",
            "subject": "merge: agent/chatgpt-local-reconcile-tomorrow-75872331e5cf"
          },
          {
            "committed_at": 1787028501,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-f8afeba7b97c",
            "sha": "78a9a6d748bc90cbfb6a60dadb1fba67c54c14b7",
            "subject": "merge: agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-2-fix-typescript-build"
          },
          {
            "committed_at": 1785337319,
            "ref": "agent/cont-05cc78",
            "sha": "7662fcd8f326bd3e56a08f80aea2c41047f1b965",
            "subject": "fix(security): bake rgba opacity values into gradient to prevent compounding"
          },
          {
            "committed_at": 1786115649,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-115646",
            "sha": "178cc2c2e1073b15898b480eb0c06d5232b343e5",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786115925,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-115922",
            "sha": "f0a8e45d3788eb030c6e1c69a6554c955616df78",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786123050,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-123043",
            "sha": "e207bb1122c6b50f7f71b29f40576143c685d318",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786123278,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-123275",
            "sha": "a97b80c7010dd01bb0fafe42c9070aa4f4b0da76",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786123907,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-123902",
            "sha": "f0a3a50c31402452843c31f4d7cca0618075349f",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786126740,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-126731",
            "sha": "b01a898d992a688f457aca41a207433a7332ca93",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786130206,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-130200",
            "sha": "652cf87335a53ce6e5b88eb67bcba25d84748d14",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786133985,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-133980",
            "sha": "2b11347a733683e968928fd48baf3f2ce97b7722",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786138974,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-138970",
            "sha": "75ff21190154116c0fd848b1589e8f487808b170",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786140949,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-140946",
            "sha": "b6006a7e011bb56e7f2b5f3f1bfffe2a1164f1f8",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786141317,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-141313",
            "sha": "a5fa12c899f49f795f5a38804213c8851f80d458",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786141443,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-141438",
            "sha": "5c5d20597d1d7c1d41da572d98ea3c06fdb25931",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786144035,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-144029",
            "sha": "4616a1ede7f97d302958e1a7b76d14ffcdc1a34a",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786155533,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-155526",
            "sha": "df0a369c3dacfcc1a2d81dcf5848d392b97915d9",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786165853,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-165847",
            "sha": "757b0849d230562b2ea95b16640a0afb6b75e9f0",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786185620,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-clean-185617",
            "sha": "8b4402816c7bbb4e6122e26d9e286344885d50b7",
            "subject": "self-heal: clean files from agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2 (13 files)"
          },
          {
            "committed_at": 1786169955,
            "ref": "agent/dropbox-economic-scheduler-revenue-revenue-focused-slice-2-patch-attorneycockpit",
            "sha": "0782234e83f2892021e1eb876fdc389a82438014",
            "subject": "regen-from-cache(template): dropbox-economic-scheduler-revenue-revenue-focused-slice-2-patch-attorneycockpit"
          },
          {
            "committed_at": 1786015069,
            "ref": "agent/dropbox-p0-t11-fix-ui-to-missing-route-calls",
            "sha": "47718dc5095e1f163d2610b99542c14e318db992",
            "subject": "agent: dropbox-p0-t11-fix-ui-to-missing-route-calls \u2014 rebase onto main, restore db:check literal"
          },
          {
            "committed_at": 1786015243,
            "ref": "agent/dropbox-p0-t7-migrate-dev-only-nitro-plugins-to-crons",
            "sha": "12730551915d97ac28535338b131c86885229497",
            "subject": "agent: dropbox-p0-t7-migrate-dev-only-nitro-plugins-to-crons \u2014 cover the remaining scheduler plugins"
          }
        ],
        "branches_total": 41,
        "count": 41,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      }
    ]
