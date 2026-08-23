PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-909331db1fdb
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
    `909331db1fdbe22cf867a4c314a7ccd82ae394e60e93535390d8a2995aef39d7`, including source, classification, disposition, and resulting task/branch/commit. Completion
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
        "head": "2fdff278965928f8c7b162f87eda067de4c08175",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/integration-worktrees/6973da69fb225e176b92"
      },
      {
        "count": 457,
        "items_digest": "1e105b70cd0ec9392fb4b6d3c37532f98f455cf780ff1bf83e4d8f33e4d39c98",
        "items_sample": [
          {
            "created_at": 1785715617,
            "ref": "refs/orch-rescue/20260803T000657-6973da69fb225e176b92",
            "sha": "023ed58f67021a65c275fcec9618f503332c6883",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715617,
            "ref": "refs/orch-rescue/20260803T000657-tomorrow",
            "sha": "70fc9e5fe9056fbfd799121b42ab86cecdb48df4",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715621,
            "ref": "refs/orch-rescue/20260803T000701-breach-remediation",
            "sha": "efc7b86752bc9ca2b7c44863474ca877ec5116a8",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715621,
            "ref": "refs/orch-rescue/20260803T000701-cade-mirror-negotiation",
            "sha": "3fdbdf403ac97b21c00f8eaf8e7923f0bbe8cf0c",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715622,
            "ref": "refs/orch-rescue/20260803T000702-cc-legacy-margin-removal",
            "sha": "ce9aeecf2eb3e90511930a54f758ad3bd6f11c3e",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715622,
            "ref": "refs/orch-rescue/20260803T000702-cc-mutual-default-fund",
            "sha": "f266db93417bdcd1f644f93a1bb2bc78d99f72a3",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715623,
            "ref": "refs/orch-rescue/20260803T000703-cc-solvency-passport",
            "sha": "6fe98a742871802d07158854679f76d12412b76a",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715623,
            "ref": "refs/orch-rescue/20260803T000703-convention-conformance-lints",
            "sha": "05c1b890d91e9fb4870c13fe655a0e5c32bc6999",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715623,
            "ref": "refs/orch-rescue/20260803T000703-curation-institutiontype-persist",
            "sha": "0d9cec79430ba3d092e90eb24a20e2eb9a53ca39",
            "subject": "On agent/curation-institutiontype-persist: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-economic-scheduler-revenue",
            "sha": "db8857517adf5330ff3adae7c1eabd9931a6ae46",
            "subject": "On agent/economic-scheduler-revenue: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-ensemble-on-hard",
            "sha": "933439f7190511266e657b18b3dd745f8c61a603",
            "subject": "On agent/ensemble-on-hard: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-ext-streaming-terms",
            "sha": "78b80f620b26931b2bbadb49b37ef8992c934a49",
            "subject": "On agent/ext-streaming-terms: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-fix-golden-syntax",
            "sha": "f8524ef083b2dcceb13bf2f6739faf87e745a86d",
            "subject": "On fix/conviction-core-golden-syntax: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715624,
            "ref": "refs/orch-rescue/20260803T000704-fix-syntax-lint-scope",
            "sha": "2304fa3d4616348868a1da1d64f212e2303c8d28",
            "subject": "On fix/syntax-lint-scope: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715625,
            "ref": "refs/orch-rescue/20260803T000705-hive-enforcement-velocity-index",
            "sha": "0e6d41fb0a7c2c5a80ec3fae8dbb3289e24cf193",
            "subject": "On agent/hive-enforcement-velocity-index: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715625,
            "ref": "refs/orch-rescue/20260803T000705-merged-diff-memory",
            "sha": "2834a4b60748f25bc8207b363c07d2384b717b31",
            "subject": "On agent/merged-diff-memory: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715626,
            "ref": "refs/orch-rescue/20260803T000706-orch-config-consumption",
            "sha": "be942de97ce0c49ca55ee34c445c3e40d7f58b28",
            "subject": "On agent/orch-config-consumption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715626,
            "ref": "refs/orch-rescue/20260803T000706-pinned-express-lane",
            "sha": "83791d8a5d941207957ec1e4a4988d7ac26be2c4",
            "subject": "On agent/pinned-express-lane: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715627,
            "ref": "refs/orch-rescue/20260803T000707-ploeh-s2s-bridge-tomorrow",
            "sha": "4311b02c9c6a4fdb2ef2c07283993c47ed522778",
            "subject": "On agent/ploeh-s2s-bridge-tomorrow: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715627,
            "ref": "refs/orch-rescue/20260803T000707-predictive-preemption",
            "sha": "39da964835be21316602687ca6057cad9fe2f030",
            "subject": "On agent/predictive-preemption: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715628,
            "ref": "refs/orch-rescue/20260803T000708-prompt-evolution-bandit",
            "sha": "881df542e6b12105f9d2bece20297413783de8b5",
            "subject": "On agent/prompt-evolution-bandit: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715629,
            "ref": "refs/orch-rescue/20260803T000709-smarter-5-95",
            "sha": "b2d3cfca656e0f6034b9bed22fcdc4476269852b",
            "subject": "On agent/smarter-5-95: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715664,
            "ref": "refs/orch-rescue/20260803T000744-tomorrow",
            "sha": "248206db911914064121a377008a2b307edcb9f2",
            "subject": "On main: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715665,
            "ref": "refs/orch-rescue/20260803T000745-6973da69fb225e176b92",
            "sha": "aa6d32a73dff4ccdc09f0a7b284a6c3328a7c82c",
            "subject": "On (no branch): orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715666,
            "ref": "refs/orch-rescue/20260803T000746-breach-remediation",
            "sha": "7d35dda6e5582bd55ad27cbcb657ea4c36882bfb",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715667,
            "ref": "refs/orch-rescue/20260803T000747-cade-mirror-negotiation",
            "sha": "1dd02d57bbd4eb886b286c5208328b87b8a7a4c3",
            "subject": "On agent/cade-mirror-negotiation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715667,
            "ref": "refs/orch-rescue/20260803T000747-cc-legacy-margin-removal",
            "sha": "6ad0a39d9e37b80abb62d256c9b603b273daa790",
            "subject": "On agent/cc-legacy-margin-removal: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715667,
            "ref": "refs/orch-rescue/20260803T000747-cc-mutual-default-fund",
            "sha": "e9d5eb396881a1faa2cbdf99ad3c502a3ed0b448",
            "subject": "On agent/cc-mutual-default-fund: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715667,
            "ref": "refs/orch-rescue/20260803T000747-cc-solvency-passport",
            "sha": "a068422735883d3719d9efac70462d170ebdc479",
            "subject": "On agent/cc-solvency-passport: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785715667,
            "ref": "refs/orch-rescue/20260803T000747-convention-conformance-lints",
            "sha": "bb8075ed05d5320ae428e324db189fc8d25b648b",
            "subject": "On agent/convention-conformance-lints: orch-rescue: periodic sweep"
          }
        ],
        "items_total": 457,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/tomorrow/tomorrow"
      }
    ]
