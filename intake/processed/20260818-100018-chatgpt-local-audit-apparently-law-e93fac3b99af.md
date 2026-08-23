PROJECT: apparently-law

- id: chatgpt-local-reconcile-apparently-law-e93fac3b99af
  title: Reconcile local ChatGPT/Codex build evidence for apparently-law
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
    `e93fac3b99afc5c69a8a27ee909138c2583e16238448116fe464f25587a50988`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "integrate/regmap-sister",
        "change_count": 1,
        "changes": [
          ".convention-rules.json"
        ],
        "changes_digest": "52b17955319c454214d9c65fe286f7f8abc398c6d3cdba375264c0f60a3f5e8e",
        "head": "d192796ebd45ad4698924734f3b7bf2c84cb41ce",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786955452,
        "path": "/Users/kpasch/Documents/apparently-law"
      },
      {
        "branch": "DETACHED",
        "change_count": 13,
        "changes": [
          "app/components/FractionalGCCalculator.vue",
          "app/components/RiskStorefrontTeaser.vue",
          "app/components/SweepsMemoAudit.vue",
          "app/components/TankSharkApplication.vue",
          "app/pages/for/ai-data.vue",
          "app/pages/for/boutique.vue",
          "app/pages/for/financial-services.vue",
          "app/pages/for/gaming.vue",
          "app/pages/for/in-house.vue",
          "app/pages/for/startups.vue",
          "app/pages/learn/videos.vue",
          "app/pages/learn/videos/[slug].vue",
          "app/pages/tankshark.vue"
        ],
        "changes_digest": "1b83d03e602f5b59bb268c128a20cb978d590edc6a5cbc8d7b8261e7ed74061b",
        "head": "9f68c67b50a1d4165c5578614c8571749d329fa5",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786071044,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/c66dbe70aa5286b2e949"
      }
    ]
