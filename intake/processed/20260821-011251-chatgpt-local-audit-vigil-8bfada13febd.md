PROJECT: vigil

- id: chatgpt-local-reconcile-vigil-8bfada13febd
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
    `8bfada13febd9f99b384363d61a5e11c4571d3b82d893e6b858aaa12554c5835`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "main",
        "change_count": 9,
        "changes": [
          ".convention-rules.json",
          "server/api/cron/vigil-autonomous-remediation.get.ts",
          "server/domain/jobs/autonomousRemediationWorker.ts",
          "supabase/migrations/20260811090000_vigil_autonomous_remediation.sql",
          "tests/autonomous-remediation.spec.ts",
          "tests/cron-access.spec.ts",
          "tests/ecosystem.spec.ts",
          "tests/examiner-agents.spec.ts",
          "vercel.json"
        ],
        "changes_digest": "0a96ab9393830c9f39499f2cb43cc6d4d98cb73d7c52913a3545e388b4024b63",
        "head": "dcdb561cae4c864280471dda897ee74ba6b9e3d7",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786955450,
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
