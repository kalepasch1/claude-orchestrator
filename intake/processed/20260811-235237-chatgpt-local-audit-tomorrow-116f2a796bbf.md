PROJECT: tomorrow

- id: chatgpt-local-reconcile-tomorrow-116f2a796bbf
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
    `116f2a796bbffde50f1c4f5dd8d9fb8bdf923f9f009d6e63168deeca68b524ee`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/contracts-smarter",
        "change_count": 7312,
        "changes_digest": "191549df2604b6880348126b30abd7633a5dac765e0473ad2335b928bc12cd73",
        "changes_sample": [
          ".browserslistrc",
          ".deploy-canary",
          ".env.example",
          ".gitattributes",
          ".github/workflows/auto-sync.yml",
          ".github/workflows/bot-commit-review.yml",
          ".github/workflows/completeness-credit-e2e.yml",
          ".github/workflows/corpus-harvest.yml",
          ".github/workflows/db-drift-check.yml",
          ".github/workflows/deploy-guard.yml",
          ".github/workflows/deploy-watcher.yml",
          ".github/workflows/migration-apply-check.yml",
          ".github/workflows/preflight.yml",
          ".github/workflows/registry-auth.yml",
          ".github/workflows/release.yml",
          ".github/workflows/repair-user-security-columns.yml",
          ".github/workflows/secrets-scan.yml",
          ".github/workflows/self-improvement-apply.yml",
          ".github/workflows/sfc-gate.yml",
          ".github/workflows/temp-login-test.yml",
          ".github/workflows/train.yml",
          ".gitignore",
          ".gitleaks.toml",
          ".husky/pre-commit",
          ".lint-catalog-baseline",
          ".merge-analysis/agent-factor-betas-feeder.md",
          ".npmrc",
          ".nvmrc",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-3-restore-missing-expor.txt",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt"
        ],
        "changes_total": 100,
        "head": "cb31262f9a49c0681bced29252d132ca75a26577",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786492152,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/contracts-smarter"
      },
      {
        "branch": "agent/rls-regression-ci-gate",
        "change_count": 7312,
        "changes_digest": "191549df2604b6880348126b30abd7633a5dac765e0473ad2335b928bc12cd73",
        "changes_sample": [
          ".browserslistrc",
          ".deploy-canary",
          ".env.example",
          ".gitattributes",
          ".github/workflows/auto-sync.yml",
          ".github/workflows/bot-commit-review.yml",
          ".github/workflows/completeness-credit-e2e.yml",
          ".github/workflows/corpus-harvest.yml",
          ".github/workflows/db-drift-check.yml",
          ".github/workflows/deploy-guard.yml",
          ".github/workflows/deploy-watcher.yml",
          ".github/workflows/migration-apply-check.yml",
          ".github/workflows/preflight.yml",
          ".github/workflows/registry-auth.yml",
          ".github/workflows/release.yml",
          ".github/workflows/repair-user-security-columns.yml",
          ".github/workflows/secrets-scan.yml",
          ".github/workflows/self-improvement-apply.yml",
          ".github/workflows/sfc-gate.yml",
          ".github/workflows/temp-login-test.yml",
          ".github/workflows/train.yml",
          ".gitignore",
          ".gitleaks.toml",
          ".husky/pre-commit",
          ".lint-catalog-baseline",
          ".merge-analysis/agent-factor-betas-feeder.md",
          ".npmrc",
          ".nvmrc",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-3-restore-missing-expor.txt",
          ".recovery-intent-adversarial-second-opinion-split-the-build-task-in-slice-5-match-prior-artifact.txt"
        ],
        "changes_total": 100,
        "head": "cb31262f9a49c0681bced29252d132ca75a26577",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786492278,
        "path": "/Users/kpasch/Documents/tomorrow/tomorrow-wt/rls-regression-ci-gate"
      }
    ]
