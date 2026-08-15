PROJECT: apparently

- id: chatgpt-local-reconcile-apparently-9f2e5c9cf747
  title: Reconcile local ChatGPT/Codex build evidence for apparently
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
    `9f2e5c9cf7478ab83848212234c7f6986f5cc2286db839dc190dc9f1d6b0d6f1`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "landing-revamp-20260811",
        "change_count": 19,
        "changes": [
          ".github/workflows/ci.yml",
          "app/pages/index.vue",
          "package.json",
          "scripts/.tmp-dryrun-525.mjs",
          "scripts/check-spine-health.mjs",
          "scripts/check-supabase-advisors.mjs",
          "supabase/migrations/20260724200000_390_legislation_tracker_2026_july24_update.sql",
          "supabase/migrations/20260804200000_391_legislation_tracker_2026_aug04_update.sql",
          "supabase/migrations/20260811140000_520_corpus_canonical_model.sql",
          "supabase/migrations/20260811160000_521_consilium_grounded_roster.sql",
          "supabase/migrations/20260811180000_522_cade_personas_expertpersona_alignment.sql",
          "supabase/migrations/20260811200000_523_regulatory_eval_corpus.sql",
          "supabase/migrations/20260811210000_524_spine_health_contract.sql",
          "supabase/migrations/20260811230000_526_gradient_outcomes.sql",
          "supabase/migrations/20260811233000_527_advisor_remediation_own_defects.sql",
          "supabase/migrations/20260812000000_528_spine_health_snapshots_and_stats.sql",
          "supabase/migrations/20260812001000_529_spine_health_measured_no_regression.sql",
          "triage-run-2026-08-11.md",
          "triage-run-2026-08-12.md"
        ],
        "changes_digest": "5addb105cfb4c71ac5fc85d06494f0cab1fcc6b610489990f8f6d3843f6de8d6",
        "head": "c36c567aeba890a7fd926afb2bce1d4129cff766",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786504350,
        "path": "/Users/kpasch/Documents/apparently"
      },
      {
        "branch": "agent/ux-orchestra-undo-and-blast-radius-20260811",
        "change_count": 3,
        "changes": [
          "server/engines/jurisdiction-fabric/gesture.ts",
          "server/engines/jurisdiction-fabric/index.ts",
          "tests/engines/jurisdiction-fabric/gesture.test.ts"
        ],
        "changes_digest": "23370ad7590a64c0110b503b77e038e895670042068128077adfe471f902b3f1",
        "head": "1e634a3207cd584390f538a85f424eb130f92338",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786519829,
        "path": "/Users/kpasch/Documents/apparently-wt/ux-orchestra-undo-and-blast-radius-20260811"
      }
    ]
