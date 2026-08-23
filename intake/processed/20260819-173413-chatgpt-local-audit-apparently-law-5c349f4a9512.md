PROJECT: apparently-law

- id: chatgpt-local-reconcile-apparently-law-5c349f4a9512
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
    `5c349f4a951218e573246bb3eac3ee361bd616c617f372103016200b8ff685b1`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "count": 182,
        "items_digest": "4fbe148d8cb2a4f742f7db14e0976e5675d0cda68d38ccba5be42c711954224f",
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
        "items_total": 182,
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
        "branch": "integrate/regmap-final",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "3f260d71126b08343a1bdab87eb9aa5b7531d37d",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787062779,
        "path": "/Users/kpasch/Documents/apparently-law-wt/regmap-final"
      }
    ]
