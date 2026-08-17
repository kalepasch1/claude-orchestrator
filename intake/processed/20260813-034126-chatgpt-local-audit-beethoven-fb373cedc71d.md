PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-fb373cedc71d
  title: Reconcile local ChatGPT/Codex build evidence for beethoven
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
    `fb373cedc71d32859ad205e643ca402ca603a900ee2a0e6e836a04a01b7e42f9`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/backlog-batch-beethoven-35584ad",
        "change_count": 760,
        "changes_digest": "668267e07397b33cc2945a16728394e3a34b84ce6e6417d70bb83a62c77349c3",
        "changes_sample": [
          ".canary-gemini-35",
          ".githooks/install.sh",
          ".githooks/pre-commit",
          ".orchestrator/test-impact-subtasks.md",
          ".pre-commit-config.yaml",
          ".recovery-intent-backlog-batch-beethoven-22ee5bc-recover-convention-conformance-lints-implement-c.txt",
          ".recovery-intent-backlog-batch-beethoven-2863be9-merge-changes.txt",
          ".recovery-intent-backlog-batch-beethoven-2863be9-update-tests.txt",
          ".recovery-intent-backlog-batch-beethoven-7371e3f-add-bandit-prompt-evolution-integrate-config-loa.txt",
          ".recovery-intent-backlog-batch-beethoven-7371e3f-add-bandit-prompt-evolution-write-convergence-te.txt",
          ".recovery-intent-backlog-batch-beethoven-a86bb21-recover-pinned-express-lane-diagnose-root-cause.txt",
          ".recovery-intent-backlog-batch-beethoven-e63dfee-apply-economic-scheduler-revenue-patch-test-and-.txt",
          ".recovery-intent-canary-claude-27-slice-3-adapt-prior-merged-patterns-extract-proven-diffs-extrac.txt",
          ".recovery-intent-canary-codex-4.txt",
          ".recovery-intent-canary-codex-5.txt",
          ".recovery-intent-canary-codex-6.txt",
          ".recovery-intent-canary-deepseek-6-fix-build-errors.txt",
          ".recovery-intent-canary-gemini-25-canary-gemini-25-setup-install-dependencies.txt",
          ".recovery-intent-canary-gemini-25-canary-gemini-25-validate-add-validation-function-create-tests.txt",
          ".recovery-intent-canary-ollama-3-17-slice-1-apply-patch-template-bf2a3f19ec30.txt",
          ".recovery-intent-canary-ollama-strong-20260730.txt",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-dropbox-apparently-merge-vigil-into-apparently-gaming-exams-for-all--master-task.txt",
          ".recovery-intent-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-2-machine-p.txt",
          ".recovery-intent-dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts-e.txt",
          ".recovery-intent-dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-2-reb.txt",
          ".recovery-intent-dropbox-wave-c-compounding-codegen-platform-spine--slice-5-update-passport-tests.txt",
          ".recovery-intent-dropbox-wave-c-compounding-codegen-platform-spine-pipeline-structure-contracts.txt",
          ".recovery-intent-improve-competitive-scanner-slice-5-run-tests.txt",
          ".recovery-intent-improve-distribute-test-runners-across-fleet-8-slice-3-ensure-prod-build-stays-g.txt"
        ],
        "changes_total": 100,
        "head": "06d63d52cb1f754ac82c4c0c2899e1ad321e7a04",
        "kind": "dirty_worktree",
        "newest_change_mtime": 0,
        "path": "/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/backlog-batch-beethoven-35584ad"
      },
      {
        "branches": [
          {
            "committed_at": 1786029792,
            "ref": "_rb",
            "sha": "fcef8e0665f9b7d79cc9f4e72734dc169e24badd",
            "subject": "agent: dropbox-wave-c-compounding-codegen-platform-spine--slice-2 \u2014 unblock train: passport digest order-independence + fail-closed expiry"
          },
          {
            "committed_at": 1785997508,
            "ref": "agent/backlog-batch-beethoven-63cf995-merged-diff-memory-implement-minimal-merged-diff",
            "sha": "1eabddf71014489ad6e903866429b800bf93d7c3",
            "subject": "agent: backlog-batch-beethoven-63cf995-merged-diff-memory-implement-minimal-merged-diff"
          },
          {
            "committed_at": 1786140994,
            "ref": "agent/copyfix-beethoven-07180848-slice-3-public-landing-founder-navigation-copy-clean-140991",
            "sha": "37a6932a8bf6b9182517d8e8405f8521fc8e5fc7",
            "subject": "self-heal: clean files from agent/copyfix-beethoven-07180848-slice-3-public-landing-founder-navigation-copy (31 files)"
          },
          {
            "committed_at": 1786048997,
            "ref": "agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-1-never-again-lane-daemon-immune-system-p0-recovered",
            "sha": "ac8d2768478a7f99d80790e7be86e6d46a9e62fa",
            "subject": "agent: fleet immune system section 1 - lane + daemon hard timeouts, locks, telemetry"
          },
          {
            "committed_at": 1786025909,
            "ref": "agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0",
            "sha": "0a175f15699b96e2d4cf27d3499dc74b83c97ec8",
            "subject": "agent: dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0"
          },
          {
            "committed_at": 1786044150,
            "ref": "agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-1",
            "sha": "3b9e58287bfc983898b18476c5d1345ce4fccb7b",
            "subject": "agent: dropbox-hisanta-mastery-engine-grandma-rail-family-slice-1"
          },
          {
            "committed_at": 1786052506,
            "ref": "agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2",
            "sha": "7065f5caf9639c96f2a1de82a366080aebcd1a78",
            "subject": "agent: dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2 \u2014 family contracts live once; mastery engine methods the contracts promised"
          },
          {
            "committed_at": 1786129454,
            "ref": "agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448",
            "sha": "358297faa18ff03172ac9f7240ce981e825e13bb",
            "subject": "self-heal: clean files from agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2 (18 files)"
          },
          {
            "committed_at": 1786052527,
            "ref": "agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3",
            "sha": "d8497ed3adea65e4a7ac43610129737ed20e3dac",
            "subject": "agent: dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3"
          },
          {
            "committed_at": 1786087016,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause",
            "sha": "886220ad6754ba34bb06d3c67c0fe5594ea5ce7f",
            "subject": "agent: dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause"
          },
          {
            "committed_at": 1786035070,
            "ref": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-billing-guard-scope",
            "sha": "a6e901f9dc32ead9aaa0d9810be154c461e8b9e2",
            "subject": "agent: dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-billing-guard-scope"
          },
          {
            "committed_at": 1786058165,
            "ref": "agent/dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2",
            "sha": "60d1a6c325b3f7ae94bbd7c778b12baf56406ae0",
            "subject": "agent: dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2"
          },
          {
            "committed_at": 1786057194,
            "ref": "agent/dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat",
            "sha": "e894c5d775c177b99fdc43ef72a3f36ddb849e53",
            "subject": "agent: dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat"
          },
          {
            "committed_at": 1785388122,
            "ref": "agent/dropbox-prediction-markets-institute-think-tank-launch-brand-exam-ap-contracts",
            "sha": "952bdd1b1838b886887137c0ccfcdcc52f24e148",
            "subject": "refactor(pricing-grid): extract capacity and consumption helpers to eliminate duplication"
          },
          {
            "committed_at": 1786026394,
            "ref": "agent/dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-4",
            "sha": "ae4f5f7d64f7653921c3f195f0f15310f6046ffe",
            "subject": "agent: dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-4"
          },
          {
            "committed_at": 1786026236,
            "ref": "agent/dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-5",
            "sha": "fbec1e7cd20bbccf7d7cf303720086a188b97f82",
            "subject": "agent: dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-5"
          },
          {
            "committed_at": 1786152447,
            "ref": "agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441",
            "sha": "dc65c5428c7ca2d3de8d2cf017ced6fa513e438c",
            "subject": "self-heal: clean files from agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a (30 files)"
          },
          {
            "committed_at": 1786026721,
            "ref": "agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-validate-repository",
            "sha": "7e17f95130b7e3927e765e372ac0165c160b0de1",
            "subject": "copyfix: rewrite hero control copy to value-level language"
          },
          {
            "committed_at": 1786151471,
            "ref": "agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469",
            "sha": "a9e98fc3c705ebcb705617f1111c1396230ef915",
            "subject": "self-heal: clean files from agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests (3 files)"
          },
          {
            "committed_at": 1785643667,
            "ref": "agent/oc-autoclear-policy",
            "sha": "300e7e1bdeb55328579b081842c8bb206309fc3b",
            "subject": "autoclear: add fallback YAML rules and fix migration syntax"
          },
          {
            "committed_at": 1785383571,
            "ref": "backlog-batch-illuminati-1d1b027",
            "sha": "0abf5b6d4c52bfc741172e9aae160743cc5bc2e3",
            "subject": "fix(backlog-batch-illuminati): timestamp in empty batch result + floating point precision in tests"
          },
          {
            "committed_at": 1786103948,
            "ref": "fix-release-train-manifest-import-20260807",
            "sha": "6d77311f95e2fe2172425395372f54eaecfbf932",
            "subject": "fix: add missing release_manifest import in release_train.py"
          },
          {
            "committed_at": 1786043518,
            "ref": "verify/cowork-batch1",
            "sha": "609c9b2afa584795f60c624f163f042a4116ce1b",
            "subject": "Merge branch 'agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-4-recovered' into verify/cowork-batch1"
          },
          {
            "committed_at": 1786043392,
            "ref": "verify/solo3",
            "sha": "f1aeea3f2bde8e845520d5d9ad48b89611d63868",
            "subject": "Merge remote-tracking branch 'origin/agent/dropbox-beethoven-audit-addendum-two-session-recon-slice-4-recovered' into verify/solo3"
          }
        ],
        "count": 24,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
