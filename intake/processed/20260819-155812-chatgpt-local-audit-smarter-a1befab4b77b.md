PROJECT: smarter

- id: chatgpt-local-reconcile-smarter-a1befab4b77b
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
    `a1befab4b77b721d3306d64864f1885b6ff88dae45a50056b9ac34606bc8510b`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 20,
        "items": [
          {
            "created_at": 1787113437,
            "ref": "stash@{1}",
            "sha": "913a45cb1c81b4bc77265a3264311fdaa89e9f52",
            "subject": "WIP on agent/contracts-smarter: ba214e3cc chore: bump pasch and prediction-markets-institute/pmi submodule pointers"
          },
          {
            "created_at": 1785411633,
            "ref": "stash@{2}",
            "sha": "92226f1e293a49c01875caa0a739fe3946e435b4",
            "subject": "WIP on review/agent-access: c53b7fff6 test: lock in the review-access safety properties"
          },
          {
            "created_at": 1784916709,
            "ref": "stash@{3}",
            "sha": "127dca052b66d6b0f32715f3010cf199c59d0d9d",
            "subject": "WIP on main: 4f3e300cd feat: role-based intelligence platform overhaul"
          },
          {
            "created_at": 1784685042,
            "ref": "stash@{4}",
            "sha": "a0cc43108eef0f44b3e7a45aa65ad869de3c8144",
            "subject": "WIP on main: 0ec77bcee Merge branch 'agent/backlog-batch-smarter-6c8e892'"
          },
          {
            "created_at": 1784684917,
            "ref": "stash@{5}",
            "sha": "1f703d03d72b4e69246f3f55dedba525bd9c2a14",
            "subject": "WIP on main: 8397d6755 fix: robust ignoreCommand (use VERCEL_GIT_PREVIOUS_SHA fallback)"
          },
          {
            "created_at": 1784684677,
            "ref": "stash@{6}",
            "sha": "c9b0d4b7dfe6b71524a916e527c9fed498019f6f",
            "subject": "On main: pre-force-merge"
          },
          {
            "created_at": 1784680445,
            "ref": "stash@{7}",
            "sha": "7b2d0e589e19a421fb66076e568595c456ac22af",
            "subject": "WIP on main: 1b41c09b6 perf: add ignoreCommand to skip builds on non-code changes"
          },
          {
            "created_at": 1784677825,
            "ref": "stash@{8}",
            "sha": "136a1afacaa2ded44411b081cf59ebe7cce659d6",
            "subject": "On main: auto-stash for push-retry"
          },
          {
            "created_at": 1784425581,
            "ref": "stash@{9}",
            "sha": "bf9933dd48e747b4da11ce16924c34658aeec554",
            "subject": "WIP on main: e78b242ab Merge remote-tracking branch 'origin/agent/copyfix-smarter-07180848-slice-5'"
          },
          {
            "created_at": 1784422595,
            "ref": "stash@{10}",
            "sha": "be96aeab543a2d11ee1b3606fd83ff383c89b09d",
            "subject": "WIP on main: 64231b2b6 feat(growth): wire the distribution flywheel into the app"
          },
          {
            "created_at": 1784422351,
            "ref": "stash@{11}",
            "sha": "c31fc24c6e2aeea52451848e1b162e138c7b55fc",
            "subject": "WIP on main: 64231b2b6 feat(growth): wire the distribution flywheel into the app"
          },
          {
            "created_at": 1784421658,
            "ref": "stash@{12}",
            "sha": "498667b7361ec313c58cba5ffb181789f9008b21",
            "subject": "On agent/cont-fdd544: cowork-cleanup-stash"
          },
          {
            "created_at": 1784173605,
            "ref": "stash@{13}",
            "sha": "4838f0fb57a31bf29660b74bec785d07a6b9d719",
            "subject": "WIP on agent/growth-foundation-wired: 8dda3c3 recovery: preserve final restored source state"
          },
          {
            "created_at": 1784172140,
            "ref": "stash@{14}",
            "sha": "78b0ae662b757a265efe0d9f38baaae15f7a77a1",
            "subject": "WIP on growth-foundation-wired: 8dda3c3 recovery: preserve final restored source state"
          },
          {
            "created_at": 1784133466,
            "ref": "stash@{15}",
            "sha": "01985b68c767ceb823e9298fbd838a54a8140cbd",
            "subject": "WIP on main: 8685ff8 chore: repair Vercel deployment attribution"
          },
          {
            "created_at": 1784002673,
            "ref": "stash@{16}",
            "sha": "242b08e3651871ef686cd31a3b7d29e78dd1cc83",
            "subject": "WIP on agent/client-ask-my-matter: 71be71d integrate: origin/wt-sweep/bx1-1783987090 into main (legacy worktree consolidation)"
          },
          {
            "created_at": 1784002247,
            "ref": "stash@{17}",
            "sha": "2a9457fdd39558c075ff8a5e06b963ddad84cd73",
            "subject": "WIP on agent/smarter-5-95: 0979ea2 feat: lint-decision-budgets enforces 5/95 rule via trust dial"
          },
          {
            "created_at": 1783986336,
            "ref": "stash@{18}",
            "sha": "24f6ad23841c73d2a0abf5562b2fafe286986b29",
            "subject": "On agent/rework-legal-recover-missing-branch-cont-0dea9b55-slice-1-bb48850: manual-restore-1783986336"
          },
          {
            "created_at": 1783971188,
            "ref": "stash@{19}",
            "sha": "cbce3ff19a8536709ad9776c5ebf419ebc68f56b",
            "subject": "WIP on qafix-smarter-07120631: 56dd195 fix: escape quote in semanticRedTeam.ts breaking build"
          },
          {
            "created_at": 1783310584,
            "ref": "stash@{20}",
            "sha": "b70cdd75fd46c4d8e6c54b639eaf2433cef8f65d",
            "subject": "On merge-train-tmp: recover_and_ship: pre-merge dirt 1783310584"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/smarter"
      }
    ]
