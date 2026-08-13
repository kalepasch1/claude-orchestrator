# Stranded agent branches — inventory

Generated 2026-08-12T13:18:16.287926+00:00 against `origin/master`.
Read-only inventory. No branch was merged and no task state was changed to
produce it.

## Totals

- agent/* branches on origin: **967**
- already merged into master: **761**
- **STRANDED (not an ancestor of master): 206**
  - merge cleanly today: **141**
  - would conflict: **65**

- real source lines added across the stranded set: **275,119**
- lines excluded as lockfile / build output / vendored / binary: 0

The excluded figure is why the raw ~1.28M insertion count must not be quoted as
recoverable work. Only the source figure above represents human output.

## Root cause — confirmed, already fixed

Commit `7ec2d4e` (`fix(merge): scan-window starvation — the real cause of months of
stranded work`) is **already an ancestor of master**, and it does explain this
backlog. `_pick_cards()` scanned only the NEWEST 3,000 approved cards out of 238,177
rows, and the train stamps `decided_by` on every card it handles — so the newest
3,000 were almost entirely already-decided outcomes. A card not merged immediately
aged out of that window within hours and became invisible forever, while
`ensure_integration_card` still found it and refused to file a replacement, so the
task could not be re-queued either. That is both why 'undecided cards = 0' was
reported alongside 90 waiting tasks, and why finished work went 'merged, plausible,
inert' for months. The fix scans oldest-first as well and took `_pick_cards()` from
effectively 0 actionable cards to 103.

**This task is therefore about draining the backlog that fix explains, not
re-diagnosing it.**

## Not to be confused with the phantom tasks

The 10,224 PHANTOM_UNVERIFIED tasks are a different population and are NOT
recoverable: mechanism M3_bulk_update alone covers 6,256 of them and has 0 branches,
1 commit and 39 artifacts between them — they mostly produced nothing, so they can
only be re-run. The branches below are the opposite case: the code exists.

## Recovery rules

- Clean branches are requeued as the ORIGINAL task with a `-recovered` slug suffix so
  they re-enter the normal pipeline and pass the normal gates. They are **not** merged
  directly to master and do **not** bypass the merge train, QA, or the release train.
- Every requeue is an individual insert carrying its own provenance note. No bulk
  state change, ever.
- Nothing is marked MERGED that has not actually merged.
- A branch whose original task row is gone is still inventoried; no task is invented
  for it.
- Conflicting branches are classified superseded / still-wanted / unclear, and
  ambiguity resolves to **unclear** rather than to a guess.

## Branches that merge cleanly

| branch | age (d) | src +/- | files | task state |
|---|---:|---:|---:|---|
| `canary-codex-31` | 12.7 | +8/-0 | 2 | — no task row — |
| `remediate-dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-c` | 12.4 | +1/-0 | 1 | — no task row — |
| `canary-codex-53` | 11.1 | +34/-0 | 1 | — no task row — |
| `qafix-beethoven-08020135` | 10.3 | +4/-0 | 1 | — no task row — |
| `backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-add-test-checks` | 10.0 | +4/-0 | 1 | — no task row — |
| `improve-enhanced-testing-pipeline-missing-branch-r-slice-1` | 10.0 | +346/-4 | 2 | — no task row — |
| `improve-pre-decomposition-branch-availability-ve-slice-3-implement-bootstrap-inj` | 9.9 | +601/-0 | 3 | — no task row — |
| `qafix-beethoven-08021822` | 9.7 | +4/-0 | 1 | — no task row — |
| `copyfix-beethoven-07180848-slice-3-public-landing-hero-control-copy` | 6.6 | +4/-4 | 1 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-4` | 6.4 | +474/-0 | 3 | — no task row — |
| `recover-missing-branch-backlog-batch-apparently-0d157dd-fix-render-decision-briefs-review` | 6.4 | +397/-2 | 4 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-logging` | 6.3 | +4/-0 | 1 | — no task row — |
| `copyfix-beethoven-07180848-slice-3-public-landing-founder-navigation-copy` | 6.3 | +1/-1 | 1 | — no task row — |
| `improve-missing-branch-auto-creator-slice-3-connect-event-to-branch-creation` | 6.2 | +127/-1 | 2 | — no task row — |
| `copyfix-beethoven-07180848-slice-3-public-landing-portfolio-objectives-copy` | 6.1 | +1/-1 | 1 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-1` | 6.1 | +1259/-3 | 6 | — no task row — |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-1` | 5.9 | +254/-27 | 3 | — no task row — |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-billing-guard-scope` | 5.9 | +514/-76 | 2 | — no task row — |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-db-env-loader-guard` | 5.9 | +247/-7 | 3 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-4-recovered` | 5.8 | +474/-0 | 3 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-1-recovered` | 5.8 | +1235/-0 | 5 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-2-recovered` | 5.7 | +644/-3 | 3 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5-recovered` | 5.7 | +209/-1 | 2 | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-a-slice-1` | 5.7 | +876/-3 | 7 | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-a-slice-2` | 5.7 | +185/-12 | 2 | — no task row — |
| `dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-2-recovered` | 5.7 | +165/-0 | 1 | — no task row — |
| `release-on-capacity-not-clock-cowork-20260806` | 5.7 | +308/-29 | 3 | — no task row — |
| `relfix-vercel-checks-cache-fix-runner-emit-task-log` | 5.7 | +165/-0 | 1 | — no task row — |
| `salvage-recovery-engine-wip-20260806` | 5.7 | +1179/-0 | 4 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-2` | 5.6 | +644/-3 | 3 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-3` | 5.6 | +696/-0 | 2 | — no task row — |
| `improve-upgrade-to-a-high-performance-database-slice-3-integrate-new-module` | 5.6 | +163/-32 | 4 | — no task row — |
| `canary-codex-31-detect-expired-heartbeats` | 3.8 | +4/-0 | 1 | — no task row — |
| `canary-codex-58-finalize-and-commit-commit-and-push-fixes` | 3.8 | +4/-0 | 1 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-5-rebase-and-verify` | 3.8 | +4/-0 | 1 | — no task row — |
| `canary-deepseek-6-run-full-canary-validation-run-e2e-tests` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-deepseek-6-run-full-canary-validation-run-integration-tests-pass` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-deepseek-6-run-full-canary-validation-run-smoke-tests` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-metrics-background-thread-create-http-server` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-metrics-background-thread-integrate-with-canar` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-metrics-background-thread-test-http-server` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-metrics-http-server-setup` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-metrics-update-gauge-on-success` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-setup-add-basic-main-function-setup-import-dot` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-setup-add-basic-main-function-setup-import-pro` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-setup-create-python-script-create-python-file` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-setup-create-requirements-file-create-requirem` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-logging-a` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-logging-e` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-logging-i` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-configure-bas` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-implement-val` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-test-validate` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-create-pytest-test-script-add-canary-` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-integrate-validation-and-exit-code-cr` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-integrate-validation-and-exit-code-ha` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-integrate-validation-and-exit-code-mo` | 3.7 | +4/-0 | 1 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-integrate-validation-and-exit-code-ve` | 3.7 | +4/-0 | 1 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5-e-n` | 3.7 | +4/-0 | 1 | — no task row — |
| `dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-2-reb` | 3.7 | +4/-0 | 1 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-5-reconcile-passport-te` | 3.7 | +4/-0 | 1 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-5-resolve-passport-sour` | 3.7 | +8/-0 | 2 | — no task row — |
| `dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-3-res` | 1.8 | +8/-0 | 2 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5-sen` | 1.5 | +8/-0 | 2 | — no task row — |
| `p0-phantom-unverified-triage-20260811` | 1.3 | +339/-0 | 2 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-1-recovered-adapt-patch` | 1.2 | +687/-0 | 3 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5-adapt-prior-patch` | 1.2 | +470/-0 | 3 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5-add-acceptance-test` | 1.2 | +188/-0 | 2 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5-analyze-existing-bran` | 1.2 | +530/-0 | 3 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5-extract-patch-templat` | 1.2 | +547/-0 | 3 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5-implement-core-logic` | 1.2 | +225/-7 | 2 | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts-s` | 1.2 | +48/-0 | 1 | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts-t` | 1.2 | +595/-0 | 2 | — no task row — |
| `dropbox-prompt-merged-diff-memory-system-task-spec-slice-2` | 1.2 | +253/-1 | 3 | — no task row — |
| `dropbox-prompt-merged-diff-memory-system-task-spec-slice-3` | 1.2 | +197/-0 | 2 | — no task row — |
| `dropbox-prompt-merged-diff-memory-system-task-spec-slice-5` | 1.2 | +192/-9 | 2 | — no task row — |
| `dropbox-release-pipeline-completion-windows-half-life-carding-finger-group-1-out` | 1.2 | +489/-0 | 3 | — no task row — |
| `dropbox-release-pipeline-completion-windows-half-life-carding-finger-group-1-ses` | 1.2 | +542/-0 | 2 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-2-add-narrowest-test` | 1.2 | +123/-0 | 1 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-2-find-owner-module` | 1.2 | +110/-0 | 1 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-2-reuse-project-helpers` | 1.2 | +137/-0 | 1 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5-draft-minimal-test` | 1.1 | +82/-0 | 1 | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts-d` | 1.1 | +425/-0 | 3 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-1-establish-contract-in` | 1.1 | +436/-0 | 7 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-5-refactor-passport-dar` | 1.1 | +24/-7 | 1 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-5-update-passport-tests` | 1.1 | +122/-7 | 2 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-2` | 1.0 | +484/-5 | 4 | — no task row — |
| `canary-ollama-3-4` | 0.9 | +225/-7 | 2 | — no task row — |
| `canary-ollama-4-3` | 0.9 | +225/-7 | 2 | — no task row — |
| `chatgpt-local-reconcile-beethoven-21bc760c4d1d` | 0.2 | +7012/-130 | 94 | — no task row — |
| `chatgpt-local-reconcile-beethoven-286879fa5fe4` | 0.2 | +44697/-0 | 6 | — no task row — |
| `chatgpt-local-reconcile-beethoven-44d6bb63e4fc` | 0.2 | +44697/-0 | 6 | — no task row — |
| `chatgpt-local-reconcile-beethoven-6e398b6bdfef` | 0.2 | +11548/-0 | 3 | — no task row — |
| `chatgpt-local-reconcile-beethoven-7b6f925e1e7a` | 0.2 | +386/-140 | 18 | — no task row — |
| `chatgpt-local-reconcile-beethoven-8e45bfd2cc58` | 0.2 | +792/-0 | 2 | — no task row — |
| `chatgpt-local-reconcile-beethoven-a92ff481c0ba` | 0.2 | +595/-0 | 2 | — no task row — |
| `chatgpt-local-reconcile-beethoven-d64eac25eb52` | 0.2 | +22591/-0 | 4 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-1-integrate-core-logic` | 0.2 | +312/-0 | 3 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-1-refactor-for-cleanlin` | 0.2 | +382/-14 | 2 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-1-verify-behavioral-equ` | 0.2 | +235/-0 | 1 | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5-test-and-commit` | 0.2 | +6970/-149 | 96 | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts-c` | 0.2 | +938/-10 | 11 | — no task row — |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3-integrate-adapted-cha` | 0.2 | +300/-122 | 5 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-1-define-core-types-cre` | 0.2 | +11/-0 | 1 | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-1-define-core-types-def` | 0.2 | +526/-0 | 9 | — no task row — |
| `improve-compliance-api-auth-tenancy` | 0.2 | +7435/-146 | 99 | — no task row — |
| `improve-compliance-calibrated-optimization` | 0.2 | +784/-0 | 2 | — no task row — |
| `improve-compliance-evidence-vault` | 0.2 | +887/-0 | 2 | — no task row — |
| `improve-compliance-regulatory-ingestion` | 0.2 | +952/-0 | 2 | — no task row — |
| `improve-compliance-scheduling-observability` | 0.2 | +7603/-141 | 99 | — no task row — |
| `improve-queue-dirty-checkout-auto-recovery` | 0.2 | +904/-0 | 2 | — no task row — |
| `improve-queue-prevent-darwin-passport-conflicts` | 0.2 | +707/-0 | 4 | — no task row — |
| `improve-queue-prevent-live-runner-merge-conflicts` | 0.2 | +804/-0 | 2 | — no task row — |
| `improve-release-deploy-ui-evidence-closure` | 0.2 | +813/-0 | 2 | — no task row — |
| `improve-runner-credential-capacity-failover` | 0.2 | +846/-0 | 3 | — no task row — |
| `improve-runner-supervisor-single-owner` | 0.2 | +1014/-0 | 3 | — no task row — |
| `p1-artifact-commit-fanout-is-not-evidence-20260812` | 0.2 | +5186/-0 | 5 | — no task row — |
| `relfix-pinned-claim-escape-pr-22` | 0.2 | +169/-0 | 2 | — no task row — |
| `fix-canonical-enqueue-trigger-regression-20260812` | 0.1 | +7240/-130 | 98 | — no task row — |
| `improve-compliance-durable-event-router` | 0.1 | +928/-0 | 3 | — no task row — |
| `relfix-v15-apparently-ce3433f9` | 0.1 | +7027/-131 | 99 | — no task row — |
| `triage-orch-rescue-refs-backlog` | 0.1 | +7118/-130 | 99 | — no task row — |
| `backlog-batch-beethoven-22ee5bc-convention-conform-slice-5` | 0.0 | +246/-72 | 3 | — no task row — |
| `cade-contracts` | 0.0 | +116/-0 | 1 | — no task row — |
| `canary-claude-27-slice-1` | 0.0 | +165/-49 | 3 | — no task row — |
| `canary-codex-46` | 0.0 | +26/-14 | 1 | — no task row — |
| `canary-codex-55` | 0.0 | +36/-6 | 2 | — no task row — |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-validate-` | 0.0 | +27/-17 | 2 | — no task row — |
| `convention-conformance-lints` | 0.0 | +540/-0 | 3 | — no task row — |
| `copyfix-beethoven-07180848-slice-5-recovered` | 0.0 | +1/-1 | 1 | — no task row — |
| `cross-app-knowledge-bus` | 0.0 | +157/-2 | 2 | — no task row — |
| `cx-determination-slo` | 0.0 | +445/-0 | 2 | — no task row — |
| `cx-shadow-cade` | 0.0 | +402/-0 | 2 | — no task row — |
| `deploy-journey-verification` | 0.0 | +89/-3 | 2 | — no task row — |
| `improve-automate-branch-management-slice-3` | 0.0 | +244/-2 | 2 | — no task row — |
| `improve-upgrade-to-a-high-performance-database-slice-3-implement-changes` | 0.0 | +115/-5 | 2 | — no task row — |
| `merged-diff-memory` | 0.0 | +142/-18 | 2 | — no task row — |
| `recover-stranded-agent-branches-cowork-20260806-slice-2` | 0.0 | +572/-6 | 5 | — no task row — |
| `relfix-beethoven-299c6b3c3bc6-recovered` | 0.0 | +96/-755 | 186 | — no task row — |
| `rls-regression-ci-gate` | 0.0 | +197/-5 | 4 | — no task row — |
| `runner-heartbeat-fix` | 0.0 | +110/-2 | 3 | — no task row — |

## Branches that would conflict

| branch | age (d) | src +/- | files | class | task state |
|---|---:|---:|---:|---|---|
| `approval-digest-batching` | 40.5 | +741/-22 | 5 | unclear | — no task row — |
| `orch-cross-project-depends` | 27.8 | +120/-10 | 5 | unclear | — no task row — |
| `copyfix-beethoven-07180848-slice-3` | 24.7 | +299/-0 | 1 | unclear | — no task row — |
| `copyfix-beethoven-07180848-slice-5` | 24.7 | +299/-0 | 1 | unclear | — no task row — |
| `v15-fractal-runtime` | 17.0 | +5087/-11 | 44 | unclear | — no task row — |
| `dropbox-apparently-merge-vigil-into-apparently-gaming-exams-for-all--master-task` | 15.3 | +4/-0 | 1 | unclear | — no task row — |
| `canary-codex-17` | 13.0 | +2/-3 | 2 | unclear | — no task row — |
| `canary-codex-34` | 12.5 | +32/-2 | 3 | unclear | — no task row — |
| `canary-codex-39` | 12.4 | +74/-12 | 5 | unclear | — no task row — |
| `qafix-beethoven-08010307` | 10.6 | +28/-0 | 1 | unclear | — no task row — |
| `canary-xai-6` | 9.8 | +2158/-0 | 5 | unclear | — no task row — |
| `relfix-beethoven-299c6b3c3bc6` | 8.5 | +2/-2 | 1 | unclear | — no task row — |
| `orch-config-consumption` | 7.9 | +22/-9 | 2 | unclear | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-2-machine-pipeline-heartbeat-alerts-p0` | 6.8 | +650/-0 | 4 | unclear | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-proofs` | 6.8 | +1481/-0 | 8 | unclear | — no task row — |
| `improve-missing-branch-auto-creator-slice-3-finalize-build-and-config` | 6.7 | +133/-1299 | 11 | unclear | — no task row — |
| `improve-missing-branch-auto-creator-slice-3-fix-base-branch-detection` | 6.7 | +133/-1299 | 11 | unclear | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-3` | 6.4 | +664/-2 | 4 | unclear | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5` | 6.4 | +514/-5 | 3 | unclear | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-1` | 6.4 | +551/-7 | 5 | unclear | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-3` | 6.4 | +528/-5 | 4 | unclear | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts` | 6.4 | +698/-5 | 4 | unclear | — no task row — |
| `dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-3` | 6.4 | +277/-13 | 3 | unclear | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-4` | 6.4 | +514/-5 | 3 | unclear | — no task row — |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-5` | 6.4 | +925/-5 | 6 | unclear | — no task row — |
| `perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-inspect-and-re` | 6.4 | +50/-48 | 29 | unclear | — no task row — |
| `recover-missing-branch-perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-inspect-and-re` | 6.4 | +50/-48 | 29 | unclear | — no task row — |
| `canary-gemini-25-canary-gemini-25-metrics-prometheus-setup` | 6.3 | +78/-2 | 2 | unclear | — no task row — |
| `perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-run-tests` | 6.3 | +31/-11 | 5 | unclear | — no task row — |
| `recover-missing-branch-perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-fix-typescript` | 6.3 | +50/-48 | 29 | unclear | — no task row — |
| `prompt-evolution-bandit` | 6.2 | +17/-4 | 1 | unclear | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-1` | 6.1 | +633/-3 | 4 | unclear | — no task row — |
| `improve-missing-branch-auto-creator-slice-3-finalize-build-and-config-clean-015255` | 6.1 | +118/-493 | 3 | unclear | — no task row — |
| `improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a` | 6.1 | +727/-2 | 5 | unclear | — no task row — |
| `improve-missing-branch-auto-creator-slice-3-fix-base-branch-detection-clean-022922` | 6.0 | +118/-493 | 3 | unclear | — no task row — |
| `improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module` | 6.0 | +5424/-21 | 33 | unclear | — no task row — |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-hermetic-worktree-preflight` | 5.9 | +487/-0 | 2 | unclear | — no task row — |
| `improve-missing-branch-auto-recovery-fleet-wide-slice-3-implement-pattern-adapta` | 5.9 | +5897/-27 | 40 | unclear | — no task row — |
| `copyfix-beethoven-07180848-slice-3-public-landing-domain-intent-labels-copy` | 5.8 | +7450/-56 | 51 | unclear | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-3-recovered` | 5.8 | +664/-2 | 4 | unclear | — no task row — |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-1-never-again-lane-daemon-immune-system-p0-recovered` | 5.8 | +1147/-12 | 12 | unclear | — no task row — |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2` | 5.8 | +394/-78 | 5 | unclear | — no task row — |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3` | 5.8 | +221/-35 | 2 | unclear | — no task row — |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-single-supervisor` | 5.8 | +6386/-48 | 46 | unclear | — no task row — |
| `dropbox-operator-gate-amendment-auto-ship-authoriz-slice-2` | 5.8 | +543/-1 | 5 | unclear | — no task row — |
| `dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-subscription-tier-mon` | 5.8 | +927/-0 | 6 | unclear | — no task row — |
| `dropbox-portfolio-doctrine-shared-services-x-items-slice-1` | 5.8 | +478/-1 | 5 | unclear | — no task row — |
| `improve-missing-branch-auto-creator-slice-3-finalize-build-and-config-clean-039138` | 5.8 | +118/-493 | 3 | unclear | — no task row — |
| `recover-missing-branch-dropbox-v4-global-pass-remediations-cross-app-coor-slice-1` | 5.8 | +425/-0 | 3 | unclear | — no task row — |
| `backlog-batch-beethoven-c7f3145` | 5.7 | +69/-0 | 2 | unclear | — no task row — |
| `backlog-batch-beethoven-e63dfee-apply-economic-scheduler-revenue-patch-apply-pat` | 5.7 | +55/-1 | 2 | unclear | — no task row — |
| `done-to-merged-is-the-new-bottleneck-cowork-20260806` | 5.7 | +937/-4 | 4 | unclear | — no task row — |
| `dropbox-pareto-life-goal-autonomy-stack-p4-household-legal-doc-updater-notificat` | 5.7 | +378/-0 | 3 | unclear | — no task row — |
| `improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a-clean-043991` | 5.7 | +5861/-23 | 38 | unclear | — no task row — |
| `improve-missing-branch-auto-recovery-fleet-wide-slice-3-implement-missing-branch` | 5.7 | +842/-4 | 6 | unclear | — no task row — |
| `improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests` | 5.7 | +247/-97 | 4 | unclear | — no task row — |
| `backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-implement-performance-tr` | 5.6 | +605/-8 | 2 | unclear | — no task row — |
| `backlog-batch-beethoven-22ee5bc-remaining-stale-backlog-items` | 5.6 | +503/-13 | 3 | unclear | — no task row — |
| `canary-gemini-25-canary-gemini-25-metrics-create-gauge-define-canary-last-succes` | 5.6 | +220/-2 | 2 | unclear | — no task row — |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause` | 5.6 | +181/-9 | 2 | unclear | — no task row — |
| `dropbox-prompt-merged-diff-memory-system-task-spec-group-10` | 5.6 | +689/-13 | 4 | unclear | — no task row — |
| `dropbox-prompt-merged-diff-memory-system-task-spec-group-19-wire-merge-detection` | 5.6 | +279/-2 | 2 | unclear | — no task row — |
| `factory-unblock-improve-immediate-auto-merge-on-te-slice-4-fix-compilation-types` | 5.6 | +148/-44 | 29 | unclear | — no task row — |
| `improve-value-aware-test-routing-early-exit-r-slice-3-add-early-exit-for-low-ev` | 5.5 | +437/-2 | 2 | unclear | — no task row — |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-1-integrate-adapted-dif` | 1.1 | +102/-4 | 1 | unclear | — no task row — |
