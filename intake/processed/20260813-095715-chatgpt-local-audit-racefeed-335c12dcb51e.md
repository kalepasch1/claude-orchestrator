PROJECT: racefeed

- id: chatgpt-local-reconcile-racefeed-335c12dcb51e
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
    `335c12dcb51ebc3cfa0dc2383c909a8847cb935d6f888654f110c065440d9568`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 504,
        "items_digest": "5deb7629c124176c7f8c72d37aa7cf234782aca4360c87f6301a1bf0f1acbf4c",
        "items_sample": [
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-c129734ad13bbee1e964",
            "sha": "4e7e86ff6f80dad2280413f2d0d5e485aa2ba1d6",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-c129734ad13bbee1e964-run-10003-1785714283532053000",
            "sha": "7cd5e0cf9082a898d053a7a17002763821313edb",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-c129734ad13bbee1e964-run-10250-1785715032492371000",
            "sha": "7cd5e0cf9082a898d053a7a17002763821313edb",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715600,
            "ref": "refs/orch-rescue/20260803T000640-racefeed",
            "sha": "b4939da0fa03dd1feba5f09c793f26c7b38228c4",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-1062-1785714246095212000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-11612-1785702608206761000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-12006-1785711020144387000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-12388-1785713360538091000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-12448-1785703241539186000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-14209-1785701171387059000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-15949-1785712120354334000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-17048-1785704623361813000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-17705-1785704242223916000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-18152-1785702659363173000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-1841-1785703183797676000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-18884-1785703675300363000",
            "sha": "2ad44c9d34108a74aae99d308925ac78bbbb983b",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715601,
            "ref": "refs/orch-rescue/20260803T000641-c129734ad13bbee1e964-run-1904-1785711842749694000",
            "sha": "8b2006e360ac371ba673d5d3d9d52b52cc51cc64",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-23271-1785703308068809000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-2419-1785702539401135000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-24375-1785703972292415000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-24921-1785705658250344000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-25413-1785701874685170000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-25451-1785711082523069000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-26090-1785714486918844000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-2779-1785713287902734000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-28279-1785715124821854000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-28297-1785712211071765000",
            "sha": "4f10e249654256be1139d0244afcc827e02faad0",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-30547-1785704287844482000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715602,
            "ref": "refs/orch-rescue/20260803T000642-c129734ad13bbee1e964-run-32777-1785703371604035000",
            "sha": "73706cb64aec6902dc2b1c8309869e8705ffdbf3",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715603,
            "ref": "refs/orch-rescue/20260803T000643-c129734ad13bbee1e964-run-33673-1785710580945483000",
            "sha": "5741033c38e4fdc3690db445ff8c125334343720",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          }
        ],
        "items_total": 504,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/galop/racefeed"
      }
    ]
