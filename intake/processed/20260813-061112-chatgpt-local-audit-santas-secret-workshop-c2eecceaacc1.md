PROJECT: santas-secret-workshop

- id: chatgpt-local-reconcile-santas-secret-workshop-c2eecceaacc1
  title: Reconcile local ChatGPT/Codex build evidence for santas-secret-workshop
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
    `c2eecceaacc1a17f258df4c0961974c5f8d8ec303857f11aab97f3e2270d99af`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786108646,
            "ref": "agent/consensus-engine-spec-fix-auto-filer-409-handler",
            "sha": "a89ad6dc12c1c64c0f130df80a3c10702ad522a5",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pri-slice-4' (auto-resolved)"
          },
          {
            "committed_at": 1786108655,
            "ref": "agent/rework-noop-reroute-model-keys-mock-darwin-live-model-env-gate-e9f7544",
            "sha": "2b6c00c21bd4110470c79ad4e9d6e5bc691f8c65",
            "subject": "Merge branch 'agent/dropbox-santas-secret-workshop-hisanta-premium-pricing-earnable-free-group-2' (auto-resolved)"
          }
        ],
        "count": 2,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/hisanta"
      },
      {
        "count": 127,
        "items_digest": "1f35767b6168bada4bddb09a5fc2bd22fb7b1effab764bbc7fefb851ffaf36e0",
        "items_sample": [
          {
            "created_at": 1785715629,
            "ref": "refs/orch-rescue/20260803T000709-cade-mirror-negotiation",
            "sha": "e4a48b8cfaf4761dc233f729c088924a199fa51e",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715629,
            "ref": "refs/orch-rescue/20260803T000709-hisanta",
            "sha": "6282b9cd8382f93fbd60fe449819ce6d18441052",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715630,
            "ref": "refs/orch-rescue/20260803T000710-cc-legacy-margin-removal",
            "sha": "a3cb5c85fa8172a9fc3f209833cf676678083135",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715630,
            "ref": "refs/orch-rescue/20260803T000710-cc-mutual-default-fund",
            "sha": "3f3b27e2f5b3fbc4db06a2a49f6adf7eb4afec3e",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715630,
            "ref": "refs/orch-rescue/20260803T000710-convention-conformance-lints",
            "sha": "57db212862687cc05400e83ce71b4cbd9963dc08",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715631,
            "ref": "refs/orch-rescue/20260803T000711-economic-scheduler-revenue",
            "sha": "6f85ee27ef78a454bd29b25e96588567d8f27925",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715631,
            "ref": "refs/orch-rescue/20260803T000711-ensemble-on-hard",
            "sha": "bcfe5ea65623af479e10b13601ae07edf2183df2",
            "subject": "On agent/ensemble-on-hard: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715631,
            "ref": "refs/orch-rescue/20260803T000711-hive-enforcement-velocity-index",
            "sha": "d3c2eff0ab60b4b4a96d0a485a46b077c5d4f55f",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715631,
            "ref": "refs/orch-rescue/20260803T000711-hive-support-entity-relationship-source",
            "sha": "7ee07372233513fa7872461d2845642117c973c7",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715632,
            "ref": "refs/orch-rescue/20260803T000712-merged-diff-memory",
            "sha": "162196d44e8fcb747c4ac3206c8d1d0ffee82689",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715632,
            "ref": "refs/orch-rescue/20260803T000712-orch-config-consumption",
            "sha": "bb5e028490fb1794bf5598e2cd2ada36d77e4e41",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715632,
            "ref": "refs/orch-rescue/20260803T000712-pinned-express-lane",
            "sha": "5b0abea0ce4d77857598b5ada4dad87f1391fec0",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715633,
            "ref": "refs/orch-rescue/20260803T000713-ploeh-s2s-bridge-tomorrow",
            "sha": "29be53cb51132b4105e9be29fbb7e0d97ec84d14",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715633,
            "ref": "refs/orch-rescue/20260803T000713-prompt-evolution-bandit",
            "sha": "c5d00630df07753b295d99efb47ef557041dcbd8",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715633,
            "ref": "refs/orch-rescue/20260803T000713-smarter-5-95",
            "sha": "14dc89ea0d0f90944425feb887f4b0d3057a62f2",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715669,
            "ref": "refs/orch-rescue/20260803T000749-cade-mirror-negotiation",
            "sha": "416fa1a202c4f1541857ed7b37c87139f69cd377",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715669,
            "ref": "refs/orch-rescue/20260803T000749-cc-legacy-margin-removal",
            "sha": "2a32223b43cccfd8b21a85cd2dc9617db1fc521c",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715669,
            "ref": "refs/orch-rescue/20260803T000749-cc-mutual-default-fund",
            "sha": "7962ced547a1fe9bb22e9f0f5b29ef0d4b56d9cf",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715669,
            "ref": "refs/orch-rescue/20260803T000749-convention-conformance-lints",
            "sha": "c9e2c244606e19b7f0b31692bc39845bf5537c59",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715669,
            "ref": "refs/orch-rescue/20260803T000749-hisanta",
            "sha": "ad4eed11860b52cbd3d91bad375b564326ce1dd0",
            "subject": "On master: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-economic-scheduler-revenue",
            "sha": "0d3f53184791676c06309438b358dc399b02c44e",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-ensemble-on-hard",
            "sha": "a6e99529d5deded67234c68cf6ab145c6938cd94",
            "subject": "On agent/ensemble-on-hard: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-hive-enforcement-velocity-index",
            "sha": "4257a8947bfb540105c663fc4d039a2b13b1e524",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-hive-support-entity-relationship-source",
            "sha": "ba394d8684627381c0d0008812f94106c6103b2b",
            "subject": "On agent/hive-support-entity-relationship-source: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-merged-diff-memory",
            "sha": "6782049e421d41ed59f4afe795dbd3595f375e25",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-orch-config-consumption",
            "sha": "8f2d65b918134f1fe8fef840dcff49cda754b0ff",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-pinned-express-lane",
            "sha": "96149c3f45650715510ae1901c2d0c8b92079d54",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-ploeh-s2s-bridge-tomorrow",
            "sha": "0a131a81f528ed9b788ba074b0d8964ff056941b",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-prompt-evolution-bandit",
            "sha": "fdc9baf9d82dacedfdbdd568f68f4f447e713451",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715670,
            "ref": "refs/orch-rescue/20260803T000750-smarter-5-95",
            "sha": "57039b03461c0546d8ea9f445af03f7f82eb0809",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 127,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/hisanta"
      }
    ]
