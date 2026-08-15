PROJECT: vigil

- id: chatgpt-local-reconcile-vigil-a88dda304265
  title: Reconcile local ChatGPT/Codex build evidence for vigil
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
    `a88dda304265877e8489b799c649eadebd441774400c255dcdf11e023c1f59a9`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "main",
        "change_count": 8,
        "changes": [
          "server/api/cron/vigil-autonomous-remediation.get.ts",
          "server/domain/jobs/autonomousRemediationWorker.ts",
          "supabase/migrations/20260811090000_vigil_autonomous_remediation.sql",
          "tests/autonomous-remediation.spec.ts",
          "tests/cron-access.spec.ts",
          "tests/ecosystem.spec.ts",
          "tests/examiner-agents.spec.ts",
          "vercel.json"
        ],
        "changes_digest": "fb4ec7857fddd96d9abc94657388bf3d0bb4d1f41b348b4e401daa27af525ebb",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786454849,
        "path": "/Users/kpasch/Documents/vigil"
      },
      {
        "branches": [
          {
            "committed_at": 1786075378,
            "ref": "agent/recover-missing-branch-remediate-weekly-lint-vigil-add-weekly-ci-workflow-d41219-install-dependencies",
            "sha": "ca35ea5903854ad874510d2035b1ec90b6f7ee09",
            "subject": "regen-from-cache(template): recover-missing-branch-remediate-weekly-lint-vigil-add-weekly-ci-workflow-d41219-install-dependencies"
          },
          {
            "committed_at": 1786076455,
            "ref": "agent/recover-missing-branch-remediate-weekly-lint-vigil-add-weekly-ci-workflow-d41219-setup-runtime",
            "sha": "aa234b6d4a7e228a260869295df9c9e251a3496f",
            "subject": "regen-from-cache(template): recover-missing-branch-remediate-weekly-lint-vigil-add-weekly-ci-workflow-d41219-setup-runtime"
          }
        ],
        "count": 2,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/vigil"
      },
      {
        "count": 66,
        "items_digest": "071803c8e83e1764a99c0c11692475f8cc984f66da0adc1c834c0b14ec2656a3",
        "items_sample": [
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000633-cc-mutual-default-fund",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000633-economic-scheduler-revenue",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785697756,
            "ref": "refs/orch-rescue/20260803T000633-vigil",
            "sha": "91b492289594bbfed8a831f0160dadfdffaf8b65",
            "subject": "Merge branch 'agent/weekly-lint-vigil-add-lint-notification' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000634-merged-diff-memory",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000634-ploeh-s2s-bridge-tomorrow",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000634-prompt-evolution-bandit",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785697756,
            "ref": "refs/orch-rescue/20260803T000734-vigil",
            "sha": "91b492289594bbfed8a831f0160dadfdffaf8b65",
            "subject": "Merge branch 'agent/weekly-lint-vigil-add-lint-notification' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-cc-mutual-default-fund",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-economic-scheduler-revenue",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-merged-diff-memory",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-ploeh-s2s-bridge-tomorrow",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T000735-prompt-evolution-bandit",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-cc-mutual-default-fund-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-economic-scheduler-revenue-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-merged-diff-memory-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-ploeh-s2s-bridge-tomorrow-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785594280,
            "ref": "refs/orch-rescue/20260803T001455-prompt-evolution-bandit-424a084f",
            "sha": "424a084ff5709f3638db790369e38aee4b2e3575",
            "subject": "Merge branch 'agent/weekly-lint-vigil' (auto-resolved)"
          },
          {
            "created_at": 1785697756,
            "ref": "refs/orch-rescue/20260803T001455-vigil-91b49228",
            "sha": "91b492289594bbfed8a831f0160dadfdffaf8b65",
            "subject": "Merge branch 'agent/weekly-lint-vigil-add-lint-notification' (auto-resolved)"
          },
          {
            "created_at": 1785726172,
            "ref": "refs/orch-rescue/20260803T030252-breach-remediation-6847c6f4",
            "sha": "6847c6f42ce650d86f273626e3238f004ef89899",
            "subject": "On agent/breach-remediation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785726515,
            "ref": "refs/orch-rescue/20260803T031151-vigil-a23f268c",
            "sha": "a23f268c2cfe5fa80a69a35e0a7dfdfc3255444e",
            "subject": "Merge branch 'agent/toolchain-repair-20e984ed' (auto-resolved)"
          },
          {
            "created_at": 1785728185,
            "ref": "refs/orch-rescue/20260803T065021-canary-vigil-20260727-add-update-tests-4b58138c",
            "sha": "4b58138cb190c36035c7129335031f3d4578689b",
            "subject": "recovery-intent-stub: canary-vigil-20260727-add-update-tests"
          },
          {
            "created_at": 1785728306,
            "ref": "refs/orch-rescue/20260803T075032-canary-vigil-20260727-patch-implementation-e4970bb1",
            "sha": "e4970bb11ba4c93f7818ef9a50f53c9def046a39",
            "subject": "recovery-intent-stub: canary-vigil-20260727-patch-implementation"
          },
          {
            "created_at": 1785743432,
            "ref": "refs/orch-rescue/20260803T075032-canary-vigil-20260727-run-build-tests-0c28692b",
            "sha": "0c28692b932ca43ca5d43ed9aaa1396d9672914a",
            "subject": "On agent/canary-vigil-20260727-run-build-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785753558,
            "ref": "refs/orch-rescue/20260803T103918-canary-vigil-20260727-add-update-tests-15d5e91b",
            "sha": "15d5e91b81c6d5548e0b9532879c7ec4a687a536",
            "subject": "On agent/canary-vigil-20260727-add-update-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785753559,
            "ref": "refs/orch-rescue/20260803T103919-canary-vigil-20260727-patch-implementation-29de95fb",
            "sha": "29de95fb050b28e107651f82e131ee5d8e11153f",
            "subject": "On agent/canary-vigil-20260727-patch-implementation: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785761469,
            "ref": "refs/orch-rescue/20260803T125110-canary-vigil-20260727-add-update-tests-9e212647",
            "sha": "9e212647217275ab330c41109e3cc239e5bbbc3c",
            "subject": "On agent/canary-vigil-20260727-add-update-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785762245,
            "ref": "refs/orch-rescue/20260803T130405-canary-vigil-20260727-add-update-tests-ddee936f",
            "sha": "ddee936f3a17a683549a69b57b7ae4f8b1ac3e36",
            "subject": "On agent/canary-vigil-20260727-add-update-tests: orch-rescue: periodic sweep"
          },
          {
            "created_at": 1785802001,
            "ref": "refs/orch-rescue/20260804T000944-vigil-f4d133d3",
            "sha": "f4d133d38d7a5250b433e5a1dadb80a702583411",
            "subject": "Merge branch 'agent/canary-vigil-20260731' (auto-resolved)"
          },
          {
            "created_at": 1785804830,
            "ref": "refs/orch-rescue/20260804T005509-vigil-5193a520",
            "sha": "5193a52099257be0eb56d51ca62f1dff724d0667",
            "subject": "Merge branch 'agent/relfix-vigil-07290738-fix-gate-failures' (auto-resolved)"
          },
          {
            "created_at": 1785813851,
            "ref": "refs/orch-rescue/20260804T032629-vigil-e5a43712",
            "sha": "e5a437120d55569887cb1898274a61b19f6cecb9",
            "subject": "Merge branch 'agent/relfix-vigil-07290738-commit-and-final-verify' (auto-resolved)"
          }
        ],
        "items_total": 66,
        "kind": "orchestrator_rescue_refs",
        "repo": "/Users/kpasch/Documents/vigil"
      },
      {
        "count": 1,
        "items": [
          {
            "created_at": 1784563457,
            "ref": "stash@{0}",
            "sha": "86d246cddbfd5b2b3730bb6e9381b342875e9970",
            "subject": "WIP on codex/vigil-connector-runtime: a6874df Fix release assurance workspace layout"
          }
        ],
        "kind": "stashes",
        "repo": "/Users/kpasch/Documents/vigil"
      }
    ]
