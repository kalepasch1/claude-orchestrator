PROJECT: beethoven

- id: chatgpt-local-reconcile-beethoven-4d83819ff744
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
    `4d83819ff744fb4dfdfe51ae05b9c1b9ce3e2348c2678bf59da7408f20a3ab94`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branches": [
          {
            "committed_at": 1786029792,
            "ref": "_rb",
            "sha": "fcef8e0665f9b7d79cc9f4e72734dc169e24badd",
            "subject": "agent: dropbox-wave-c-compounding-codegen-platform-spine--slice-2 \u2014 unblock train: passport digest order-independence + fail-closed expiry"
          },
          {
            "committed_at": 1785686280,
            "ref": "agent/canary-codex-55",
            "sha": "61e6fc5fe255e3edeb3a7301673f1dd0a8c6e679",
            "subject": "agent: canary-codex-55"
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
            "committed_at": 1786025919,
            "ref": "agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-proofs",
            "sha": "6364cc384a61b1bf478e4da70cd71df8043129b2",
            "subject": "agent: dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-proofs"
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
            "committed_at": 1786152447,
            "ref": "agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-152441",
            "sha": "dc65c5428c7ca2d3de8d2cf017ced6fa513e438c",
            "subject": "self-heal: clean files from agent/improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a (30 files)"
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
            "committed_at": 1786496284,
            "ref": "fix/reserved-worktree-guard-20260812",
            "sha": "6d547100836049057b28382a6b85cee8778b8cce",
            "subject": "fix(worktree): stop _free_branch force-removing an operator's worktree"
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
        "count": 23,
        "kind": "local_only_branch_tips",
        "repo": "/Users/kpasch/Documents/beethoven/claude-orchestrator"
      }
    ]
