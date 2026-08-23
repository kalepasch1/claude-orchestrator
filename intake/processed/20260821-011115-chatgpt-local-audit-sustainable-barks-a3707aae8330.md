PROJECT: sustainable-barks

- id: chatgpt-local-reconcile-sustainable-barks-a3707aae8330
  title: Reconcile local ChatGPT/Codex build evidence for sustainable-barks
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
    `a3707aae833010c479621da083bc63cc39f38f595bea4957b17b2add28403b26`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "main",
        "change_count": 3,
        "changes": [
          ".aider.chat.history.md",
          ".aider.input.history",
          ".convention-rules.json"
        ],
        "changes_digest": "1d662149d5df113ba00971e44e9761591c17b0453a005f46434be5b0aedf3e1b",
        "head": "31725a9700e3ee6506c71c5359d75c978416486b",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786955453,
        "path": "/Users/kpasch/Documents/Sustainable_Barks"
      },
      {
        "branch": "DETACHED",
        "change_count": 4,
        "changes": [
          "IMPLEMENTATION_PROMPT.md",
          "Sustainable_Barks_Strategic_Analysis.docx",
          "app.vue",
          "composables/useCanonical.ts"
        ],
        "changes_digest": "8264e9fc6b5b94944095119439d38f00b6fa524206e240e9eec3c730fd7884ae",
        "head": "45810f532c7c5b4c912d7310b415a90456d00406",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1784986420,
        "path": "/Users/kpasch/Documents/Sustainable_Barks-wt/merge-legacy-agent-funding-equilibrium"
      },
      {
        "branches": [
          {
            "committed_at": 1785677351,
            "ref": "agent/backlog-batch-sustainable-barks-d4feb77-slice-4",
            "sha": "1bc845fc6fff85f2f2fb98b25a9f0426d4b9b5a9",
            "subject": "docs: audit 35 legacy agent branches \u2014 25 merged, 10 unmerged with disposition"
          },
          {
            "committed_at": 1785677754,
            "ref": "agent/backlog-batch-sustainable-barks-d4feb77-slice-5",
            "sha": "aefce39ecc36decf9cd296a3ee6282227bf9b16b",
            "subject": "agent: backlog-batch-sustainable-barks-d4feb77-slice-5"
          },
          {
            "committed_at": 1785677556,
            "ref": "agent/canary-sustainable-barks-20260708-analyze-beethoven-branch-recovery-patch",
            "sha": "2cefd2c1858ddba5d4dddb7e827bb45c5f8a1f89",
            "subject": "docs: analyze beethoven branch recovery \u2014 25 merged, 11 unmerged, recovery plan"
          },
          {
            "committed_at": 1786060418,
            "ref": "agent/canary-sustainable-barks-20260708-analyze-beethoven-branch-recovery-patch-analyz",
            "sha": "18b2499568cd20dd74a1614613a9903c5f3183d3",
            "subject": "salvage: interrupted work for canary-sustainable-barks-20260708-analyze-beethoven-branch-recovery-patch-analyz"
          },
          {
            "committed_at": 1785677677,
            "ref": "agent/canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch",
            "sha": "e04d4ea7cbe57afc5eb1d11a0b8f6d800d199603",
            "subject": "agent: canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch"
          },
          {
            "committed_at": 1786060455,
            "ref": "agent/canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-apply-be",
            "sha": "093d48984b20602d7c32c1d3e844b7e07f674a18",
            "subject": "salvage: interrupted work for canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-apply-be"
          },
          {
            "committed_at": 1786060474,
            "ref": "agent/canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-test-and",
            "sha": "260852bf05d32cf161bef46d2a85b2f61b010855",
            "subject": "salvage: interrupted work for canary-sustainable-barks-20260708-apply-beethoven-branch-recovery-patch-test-and"
          },
          {
            "committed_at": 1785749655,
            "ref": "agent/canary-sustainable-barks-20260708-final-system-validation-run-integration-and-e2",
            "sha": "970aad6caa50ea593e414fd88f5b7ce32a79937e",
            "subject": "salvage: interrupted work for canary-sustainable-barks-20260708-final-system-validation-run-integration-and-e2"
          },
          {
            "committed_at": 1786803795,
            "ref": "agent/chatgpt-local-reconcile-sustainable-barks-0251f301b217",
            "sha": "04194dbfe4bc51eb10af3a62d99be3f7bcb348ae",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-sustainable-barks-0251f301b217"
          },
          {
            "committed_at": 1786820995,
            "ref": "agent/chatgpt-local-reconcile-sustainable-barks-48025fc82d19",
            "sha": "d3ada04730c31a1aef6888b8b0c3f841865e536c",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-sustainable-barks-48025fc82d19"
          },
          {
            "committed_at": 1786665747,
            "ref": "agent/chatgpt-local-reconcile-sustainable-barks-65b69fdf-slice-1",
            "sha": "9575a27fbada3742bb56c31b8e3d32c3a680e36a",
            "subject": "fix: add vitest devDependency so nuxi typecheck resolves tests/*.test.ts imports"
          },
          {
            "committed_at": 1786829954,
            "ref": "agent/chatgpt-local-reconcile-sustainable-barks-8ebb4ac836b5",
            "sha": "aeeb5957fb471380eeed25e407bed2a2f13548eb",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-sustainable-barks-8ebb4ac836b5"
          },
          {
            "committed_at": 1786804546,
            "ref": "agent/chatgpt-local-reconcile-sustainable-barks-9782e2f806cb",
            "sha": "83dfddc8f2559b077095844466da8d58d891b849",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-sustainable-barks-9782e2f806cb"
          },
          {
            "committed_at": 1786805445,
            "ref": "agent/chatgpt-local-reconcile-sustainable-barks-bfe099a6c0a9",
            "sha": "c41bd59faf5bfdc7074f0bdea1548c78f382d635",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-sustainable-barks-bfe099a6c0a9"
          },
          {
            "committed_at": 1786805708,
            "ref": "agent/chatgpt-local-reconcile-sustainable-barks-cc4e1a894d39",
            "sha": "008d00a665a5f284693ccf5d17b986c338a0acc8",
            "subject": "recovery-intent-stub: chatgpt-local-reconcile-sustainable-barks-cc4e1a894d39"
          },
          {
            "committed_at": 1787085674,
            "ref": "agent/qafix-sustainable-barks-08162315",
            "sha": "c1731589fedf0f421dacc4a41d0df0002e921c6c",
            "subject": "recovery-intent-stub: qafix-sustainable-barks-08162315"
          },
          {
            "committed_at": 1787081870,
            "ref": "agent/recover-be3c7c189c04-61fb1cf7416e",
            "sha": "c9a6a65bc852180f34056b3cca7df9f09d982c61",
            "subject": "recovery-intent-stub: recover-be3c7c189c04-61fb1cf7416e"
          },
          {
            "committed_at": 1787025440,
            "ref": "agent/relfix-sustainable-barks-07130241",
            "sha": "d17bf480bbf5bb2be61d76ede1fd6eaca251279a",
            "subject": "regen-from-cache(template): relfix-sustainable-barks-07130241"
          },
          {
            "committed_at": 1785682786,
            "ref": "agent/relfix-sustainable-barks-07252015",
            "sha": "754778cf0c9456a409c42d5ffdc282923c0cfebc",
            "subject": "agent: relfix-sustainable-barks-07252015"
          },
          {
            "committed_at": 1785682833,
            "ref": "agent/relfix-sustainable-barks-07252220",
            "sha": "984fef907f8cc0e6f9bb4f722845d7afdf2279d0",
            "subject": "agent: relfix-sustainable-barks-07252220"
          },
          {
            "committed_at": 1785682786,
            "ref": "agent/relfix-sustainable-barks-08011711",
            "sha": "754778cf0c9456a409c42d5ffdc282923c0cfebc",
            "subject": "agent: relfix-sustainable-barks-07252015"
          },
          {
            "committed_at": 1785972853,
            "ref": "agent/relfix-sustainable-barks-75b39426be69-rank-diff-candidates",
            "sha": "1e4480a3bfe694949213bf4b935fa6f65394a3fa",
            "subject": "agent: relfix-sustainable-barks-75b39426be69-rank-diff-candidates"
          },
          {
            "committed_at": 1786991260,
            "ref": "agent/rework-legal-rework-legal-rework-legal-rework-rework-impact-download-pri-cff5058",
            "sha": "f87448ec88acf8d72662f7894cd76d1df9d17bdf",
            "subject": "regen-from-cache(template): rework-legal-rework-legal-rework-legal-rework-rework-impact-download-pri-cff5058"
          },
          {
            "committed_at": 1785678567,
            "ref": "agent/shadow-2b186784-cowork",
            "sha": "4971ab16b96fa1e5dcaf444ca25d331a08384466",
            "subject": "recovery-intent-stub: shadow-2b186784-cowork"
          },
          {
            "committed_at": 1785679589,
            "ref": "agent/shadow-2b186784-orchestrator_native",
            "sha": "2f88a8b8d944b90c066ba2887e140829a526e313",
            "subject": "recovery-intent-stub: shadow-2b186784-orchestrator_native"
          },
          {
            "committed_at": 1787085674,
            "ref": "orchestrator/dev",
            "sha": "c1731589fedf0f421dacc4a41d0df0002e921c6c",
            "subject": "recovery-intent-stub: qafix-sustainable-barks-08162315"
          }
        ],
        "count": 26,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/Sustainable_Barks"
      },
      {
        "count": 5,
        "items": [
          {
            "created_at": 1785429738,
            "ref": "stash@{0}",
            "sha": "8a9cd1c2bc65428f6a800326c4072f5f1b126265",
            "subject": "WIP on orchestrator/dev: a82b6ff Merge agent/funding-equilibrium: cleanup obsolete composables, middleware, config artifacts"
          },
          {
            "created_at": 1784986273,
            "ref": "stash@{1}",
            "sha": "a8f8ba184283aa9ef89485646c2952ba452f365c",
            "subject": "WIP on main: 45810f5 fix: regenerate package-lock.json in sync with package.json"
          },
          {
            "created_at": 1784427673,
            "ref": "stash@{2}",
            "sha": "31b76a46c89a5f182a496515fd504ff7260de175",
            "subject": "WIP on agent/recover-missing-branch-canary-sustainable-barks-20260708-slice-1: 6285c9a agent: recover-missing-branch-canary-sustainable-barks-20260708-slice-1 \u2014 add rate-limit memory guard and test helper"
          },
          {
            "created_at": 1784427537,
            "ref": "stash@{3}",
            "sha": "d87a1cb4de8aef4da609df839d33644aeaafc6ba",
            "subject": "WIP on agent/recover-missing-branch-canary-sustainable-barks-20260708-slice-1: 6285c9a agent: recover-missing-branch-canary-sustainable-barks-20260708-slice-1 \u2014 add rate-limit memory guard and test helper"
          },
          {
            "created_at": 1783973183,
            "ref": "stash@{4}",
            "sha": "43bc336bf6008b94ae5add891018543cf8b02045",
            "subject": "WIP on main: f71e3db agent/bx2: canary-sustainable-barks-20260709 heartbeat"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/Sustainable_Barks"
      }
    ]
