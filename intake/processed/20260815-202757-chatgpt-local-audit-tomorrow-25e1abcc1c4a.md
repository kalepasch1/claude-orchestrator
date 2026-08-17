PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-25e1abcc1c4a
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
    `25e1abcc1c4a56ff21a1b73251b91d2ec53d0e0a1623cf7e0f0c255f1227f26b`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "DETACHED",
        "change_count": 1,
        "changes": [
          "packages/curation-core/node_modules/.vite/vitest/da39a3ee5e6b4b0d3255bfef95601890afd80709/results.json"
        ],
        "changes_digest": "57f90ec4d4c0896116a6af3cb2ad565771de743f6f1f96c35b413e7db8bbe304",
        "head": "7c37a231e7872f5bc0fdebbb59fcc764de99fde7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/6973da69fb225e176b92"
      },
      {
        "branches_digest": "bbcad8e6bb671791a09662cacdff1a9c1f3badb01e7b46c348ea326ceb2deaad",
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
            "committed_at": 1786572878,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-0a5088dd1715",
            "sha": "497b4a95143e2f99d90df86d2bc2abe3420d831e",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-0a5088dd1715"
          },
          {
            "committed_at": 1786651941,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-1959809d4e74-slice-1",
            "sha": "e62bd8ca798727006eb965d88e09e9f27112c8b4",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-1959809d4e74-slice-1"
          },
          {
            "committed_at": 1786654202,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-1fd5c3ff0bf2",
            "sha": "64c78dff5735408a74fbb3823bcf5200bb1c4a90",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-1fd5c3ff0bf2"
          },
          {
            "committed_at": 1786799432,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-2a509a6cf06c",
            "sha": "55b86e53092109eec1e511e89104c7464c5bac7e",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-2a509a6cf06c"
          },
          {
            "committed_at": 1786573090,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-39a7703a9f9c",
            "sha": "ad5f1814cc9342f507b4b46fb3e33d7d4e137892",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-8ce35eb9ae43"
          },
          {
            "committed_at": 1786573065,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-428d9cdff1e1",
            "sha": "4da50aa6ebd9948c6bbbb657c368c33c99f3c2ca",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-8ce35eb9ae43"
          },
          {
            "committed_at": 1786653952,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-4d4dec67d81f",
            "sha": "3e69b59edf05e178971cb3b8feaee2a24127385f",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-4d4dec67d81f \u2014 exclude deletion-only sweep artifacts from recoverable value"
          },
          {
            "committed_at": 1786573060,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-4dfa0e31aee5",
            "sha": "495e8dda4a913eb6e07e08bde9ea17fed9a77459",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-8ce35eb9ae43"
          },
          {
            "committed_at": 1786680404,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-62e3b89e03af",
            "sha": "20e2b01ebeda7efbb71c449807469a41cd4db295",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-62e3b89e03af (executable completion criteria + baseline attribution evidence)"
          },
          {
            "committed_at": 1786571830,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-711405e88745",
            "sha": "3e923d9078399ca7eb7b5b79347d14a4ba4358fb",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-7b74d4dd8e74"
          },
          {
            "committed_at": 1786571830,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-7b74d4dd8e74",
            "sha": "3e923d9078399ca7eb7b5b79347d14a4ba4358fb",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-7b74d4dd8e74"
          },
          {
            "committed_at": 1786571830,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-80bc0760d410",
            "sha": "3e923d9078399ca7eb7b5b79347d14a4ba4358fb",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-7b74d4dd8e74"
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
            "committed_at": 1786574605,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-cadcf5dad7e9",
            "sha": "41867ba0499c298d02f386581bca603677e0d751",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-8ce35eb9ae43"
          },
          {
            "committed_at": 1786799232,
            "ref": "agent/chatgpt-local-reconcile-tomorrow-d1fe07cc7ffa",
            "sha": "9d5f2dcfdd611f2c33397223f68c954ccdcbc1b1",
            "subject": "agent: chatgpt-local-reconcile-tomorrow-d1fe07cc7ffa"
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
          }
        ],
        "branches_total": 50,
        "count": 50,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      }
    ]
