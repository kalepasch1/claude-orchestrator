PROJECT: apparently-law

- id: chatgpt-local-reconcile-apparently-law-d5aa25080973
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
    `d5aa25080973e259d4ef3be506e757bfafd1b4deb5cef6fb113881dc0451dccc`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 158,
        "items_digest": "ac84a3d84a68e2b0aa8e75a9f7a29a45e2f4b74d5b07031a7dd3c8143fdae439",
        "items_sample": [
          {
            "created_at": 1785696010,
            "ref": "refs/orch-rescue/20260803T000714-cade-mirror-negotiation",
            "sha": "f2ae93bb5d01ef4c06126c7b0397baed62026e93",
            "subject": "chore(vercel): suppress preview deploys on bot/agent branches"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000714-cc-legacy-margin-removal",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000715-cc-mutual-default-fund",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000715-convention-conformance-lints",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000715-economic-scheduler-revenue",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000715-hive-enforcement-velocity-index",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000715-merged-diff-memory",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000715-orch-config-consumption",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000716-pinned-express-lane",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000716-ploeh-s2s-bridge-tomorrow",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000716-prompt-evolution-bandit",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785696010,
            "ref": "refs/orch-rescue/20260803T000750-cade-mirror-negotiation",
            "sha": "f2ae93bb5d01ef4c06126c7b0397baed62026e93",
            "subject": "chore(vercel): suppress preview deploys on bot/agent branches"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000750-cc-legacy-margin-removal",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000750-cc-mutual-default-fund",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000750-convention-conformance-lints",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000750-economic-scheduler-revenue",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000751-hive-enforcement-velocity-index",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000751-merged-diff-memory",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000751-orch-config-consumption",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000751-pinned-express-lane",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000751-ploeh-s2s-bridge-tomorrow",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T000751-prompt-evolution-bandit",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785696010,
            "ref": "refs/orch-rescue/20260803T001518-cade-mirror-negotiation-f2ae93bb",
            "sha": "f2ae93bb5d01ef4c06126c7b0397baed62026e93",
            "subject": "chore(vercel): suppress preview deploys on bot/agent branches"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T001518-cc-legacy-margin-removal-ad9fd853",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T001518-cc-mutual-default-fund-ad9fd853",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T001518-convention-conformance-lints-ad9fd853",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T001518-economic-scheduler-revenue-ad9fd853",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T001518-hive-enforcement-velocity-index-ad9fd853",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T001518-merged-diff-memory-ad9fd853",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          },
          {
            "created_at": 1785269773,
            "ref": "refs/orch-rescue/20260803T001519-orch-config-consumption-ad9fd853",
            "sha": "ad9fd853525324363835fe51620a572b6593c9fd",
            "subject": "chore: initialize apparently-law repo"
          }
        ],
        "items_total": 158,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/apparently-law"
      },
      {
        "branch": "integrate/regmap-sister",
        "change_count": 1,
        "changes": [
          ".convention-rules.json"
        ],
        "changes_digest": "52b17955319c454214d9c65fe286f7f8abc398c6d3cdba375264c0f60a3f5e8e",
        "head": "d266e47237c5891dee5d7d50d5291e37639533a6",
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
