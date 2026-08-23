PROJECT: apparently-law

- id: chatgpt-local-reconcile-apparently-law-f54cb8828d2f
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
    `f54cb8828d2fd6c72929e2f9c8f1b8ef7996823f0f71d0801a5ae50296dca770`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
        "head": "5ead2bac4637487f52b142f6cca8fb6d81bc4c76",
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
      },
      {
        "branch": "review/harden-followups",
        "change_count": 1,
        "changes": [
          "node_modules"
        ],
        "changes_digest": "0ced5e3de292ec1e8a91ae1eef1c257a4c2bd1cb856b56cfc6e535576e3b7210",
        "head": "26b72321cd6930d115af2fdd1d44d39d0f513ae0",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1787062779,
        "path": "/Users/kpasch/Documents/apparently-law-wt/regmap-review"
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
      },
      {
        "branches": [
          {
            "committed_at": 1785956638,
            "ref": "agent-local/dropbox-apparently-tomorrow-bridge-apparently-law-doc-fabric-prebuil-2-living-embed-capability-critical-dead-simple-t",
            "sha": "f7a0b0bbe89395267eef029d6e72593875918eb7",
            "subject": "agent: dropbox-apparently-tomorrow-bridge-apparently-law-doc-fabric-prebuil-2-living-embed-capability-critical-dead-simple-t"
          },
          {
            "committed_at": 1787042149,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-8361ec1c691b",
            "sha": "074fa1fd1a9b92fedaabbe43ca6c685c267572c9",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-8361ec1c691b"
          },
          {
            "committed_at": 1787042156,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-8f7038514b10",
            "sha": "e6d08d6b732333435d6772044e76cc3e43f7b4c0",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-8f7038514b10"
          },
          {
            "committed_at": 1787042145,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-b04bfeb1cdc4",
            "sha": "9bfc12ca1b77c485f83b195e6cbd7eaf67d6b545",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-b04bfeb1cdc4"
          },
          {
            "committed_at": 1787041947,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-d34eb36efdf6",
            "sha": "e7b35b878f05dd609c8bf9ed4d3591fe3b2ce97c",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-d34eb36efdf6"
          },
          {
            "committed_at": 1787040889,
            "ref": "agent/chatgpt-local-reconcile-apparently-law-db98501abecb",
            "sha": "b012719556e2f8c6aaab5ded88a825f0f1836575",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-db98501abecb"
          },
          {
            "committed_at": 1786973152,
            "ref": "integrate/regmap-final",
            "sha": "3f260d71126b08343a1bdab87eb9aa5b7531d37d",
            "subject": "regulatory map: attorney role gate, candidate import, stylesheet guard"
          },
          {
            "committed_at": 1787042156,
            "ref": "orchestrator/dev",
            "sha": "e6d08d6b732333435d6772044e76cc3e43f7b4c0",
            "subject": "agent: chatgpt-local-reconcile-apparently-law-8f7038514b10"
          }
        ],
        "count": 8,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/apparently-law"
      },
      {
        "count": 183,
        "items_digest": "22a900cd9a0b5a8260167f151a8979c94eecd9b297e5f941680566c568e52127",
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
        "items_total": 183,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/apparently-law"
      },
      {
        "count": 1,
        "items": [
          {
            "created_at": 1786941352,
            "ref": "stash@{0}",
            "sha": "751e446177225a911d9d03cf1cf6bc4be9b63758",
            "subject": "WIP on agent/chatgpt-local-reconcile-apparently-law-546a87a0dbc7: 9b3107c feat: add TankShark program, vertical landing pages, and enhanced components"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/apparently-law"
      }
    ]
