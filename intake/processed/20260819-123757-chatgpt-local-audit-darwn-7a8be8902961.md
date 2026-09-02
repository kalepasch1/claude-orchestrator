PROJECT: darwn

- id: chatgpt-local-reconcile-darwn-7a8be8902961
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
    `7a8be89029611de3d433be7e5de3c30c40b8692d8d30eb96b0eaa11771afdc58`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "master",
        "change_count": 13,
        "changes": [
          ".convention-rules.json",
          ".fleet-artifacts-moved/.recovery-intent-qafix-smarter-llm-api-retry-test-adapt-patch-template.txt",
          ".orch-context-cache.json",
          ".vercel/README.txt",
          ".vercel/project.json",
          "package-lock.json",
          "supabase/.temp/gotrue-version",
          "supabase/.temp/linked-project.json",
          "supabase/.temp/pooler-url",
          "supabase/.temp/postgres-version",
          "supabase/.temp/project-ref",
          "supabase/.temp/rest-version",
          "supabase/.temp/storage-version"
        ],
        "changes_digest": "ecb372ae8277f90143745a804f520cffaa4b3a2318cd72fad0841cee2b2ddcdd",
        "head": "3c5219ae9de0cee08008393d714a1dc33c0989d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787103460,
        "path": "/Users/kpasch/Documents/darwn/darwn"
      }
    ]
