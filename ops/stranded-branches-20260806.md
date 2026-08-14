# Stranded agent branches — inventory

Generated 2026-08-06T16:43:52.973409+00:00 against `origin/master`.
Read-only inventory. No branch was merged and no task state was changed to
produce it.

## Totals

- agent/* branches on origin: **482**
- already merged into master: **363**
- **STRANDED (not an ancestor of master): 119**
  - merge cleanly today: **103**
  - would conflict: **16**

- real source lines added across the stranded set: **39,602**
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
| `canary-codex-31` | 6.8 | +8/-0 | 2 | DECOMPOSED |
| `remediate-dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-c` | 6.6 | +1/-0 | 1 | DECOMPOSED |
| `canary-codex-53` | 5.2 | +34/-0 | 1 | SUPERSEDED |
| `qafix-beethoven-08020135` | 4.5 | +4/-0 | 1 | MERGED |
| `backlog-batch-beethoven-22ee5bc-prompt-evolution-bandit-add-test-checks` | 4.1 | +4/-0 | 1 | MERGED |
| `improve-enhanced-testing-pipeline-missing-branch-r-slice-1` | 4.1 | +346/-4 | 2 | MERGED |
| `canary-codex-55` | 4.0 | +13/-51 | 4 | QUARANTINED |
| `canary-codex-56` | 4.0 | +22/-0 | 1 | QUARANTINED |
| `improve-pre-decomposition-branch-availability-ve-slice-3-implement-bootstrap-inj` | 4.0 | +601/-0 | 3 | MERGED |
| `qafix-beethoven-08021822` | 3.9 | +4/-0 | 1 | QUARANTINED |
| `improve-pre-decomposition-branch-availability-ve-slice-3-ensure-repo-ready` | 3.8 | +406/-2 | 4 | MERGED |
| `relfix-beethoven-299c6b3c3bc6` | 2.6 | +2/-2 | 1 | MERGED |
| `orch-config-consumption` | 2.1 | +22/-9 | 2 | QUARANTINED |
| `recover-missing-branch-copyfix-beethoven-07190657-slice-3` | 1.1 | +4/-0 | 1 | QUARANTINED |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-5` | 0.9 | +209/-1 | 2 | MERGED |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-1-never-again-lane-daemon-immune-system-p0` | 0.9 | +892/-7 | 5 | MERGED |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-2-machine-pipeline-heartbeat-alerts-p0` | 0.9 | +1312/-0 | 7 | MERGED |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-3-speed-triage-routing-accelerators-p0` | 0.9 | +1857/-0 | 10 | QUEUED |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-proofs` | 0.9 | +2143/-0 | 11 | QUEUED |
| `dropbox-economic-scheduler-revenue-revenue-focused-slice-3` | 0.9 | +309/-0 | 1 | QUEUED |
| `dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-2` | 0.9 | +165/-0 | 1 | MERGED |
| `dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-4` | 0.9 | +124/-1 | 2 | MERGED |
| `dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-5` | 0.9 | +37/-0 | 1 | MERGED |
| `improve-competitive-scanner-slice-5-analyze-build-failure` | 0.9 | +4/-0 | 1 | QUEUED |
| `improve-missing-branch-auto-creator-slice-3-verify-build-and-autocreation` | 0.9 | +4/-0 | 1 | DONE |
| `backlog-batch-apparently-0d157dd-fix-render-decision-briefs-review` | 0.8 | +397/-2 | 4 | MERGED |
| `improve-missing-branch-auto-creator-slice-3-adapt-auto-branch-patch` | 0.8 | +4/-0 | 1 | DONE |
| `copyfix-beethoven-07180848-slice-3-public-landing-hero-control-copy` | 0.7 | +4/-4 | 1 | DONE |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-3` | 0.6 | +664/-2 | 4 | MERGED |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-4` | 0.6 | +474/-0 | 3 | MERGED |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-5` | 0.5 | +514/-5 | 3 | SUPERSEDED |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-1` | 0.5 | +551/-7 | 5 | SUPERSEDED |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-3` | 0.5 | +528/-5 | 4 | SUPERSEDED |
| `dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts` | 0.5 | +698/-5 | 4 | DECOMPOSED |
| `dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-3` | 0.5 | +277/-13 | 3 | SUPERSEDED |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-2` | 0.5 | +498/-9 | 4 | SUPERSEDED |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-4` | 0.5 | +514/-5 | 3 | SUPERSEDED |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-5` | 0.5 | +925/-5 | 6 | QUEUED |
| `perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-inspect-and-re` | 0.5 | +50/-48 | 29 | DONE |
| `perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-run-tests` | 0.5 | +31/-11 | 5 | MERGED |
| `recover-missing-branch-backlog-batch-apparently-0d157dd-fix-render-decision-briefs-review` | 0.5 | +397/-2 | 4 | QUARANTINED |
| `recover-missing-branch-dropbox-economic-scheduler-revenue-revenue-focused-slice-3` | 0.5 | +309/-0 | 1 | QUARANTINED |
| `recover-missing-branch-perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-fix-typescript` | 0.5 | +50/-48 | 29 | QUARANTINED |
| `recover-missing-branch-perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-inspect-and-re` | 0.5 | +50/-48 | 29 | QUEUED |
| `backlog-batch-beethoven-22ee5bc-convention-conform-slice-2` | 0.4 | +16/-0 | 1 | DONE |
| `backlog-batch-beethoven-3d08f8a` | 0.4 | +198/-0 | 2 | DONE |
| `backlog-batch-beethoven-63cf995` | 0.4 | +152/-0 | 2 | DONE |
| `backlog-batch-beethoven-63cf995-merged-diff-memory-implement-minimal-merged-diff` | 0.4 | +163/-4 | 2 | DONE |
| `backlog-batch-beethoven-e63dfee-apply-economic-scheduler-revenue-patch-locate-an` | 0.4 | +47/-0 | 2 | DONE |
| `canary-claude-27-slice-3-update-tests-checks-write-failing-test-run-and-verify-f` | 0.4 | +81/-0 | 1 | DONE |
| `canary-codex-24` | 0.4 | +47/-2 | 2 | DONE |
| `canary-codex-35` | 0.4 | +74/-0 | 1 | DONE |
| `canary-codex-4` | 0.4 | +42/-0 | 2 | DONE |
| `canary-codex-48` | 0.4 | +7/-1 | 1 | DONE |
| `canary-gemini-25-canary-gemini-25-metrics-prometheus-setup` | 0.4 | +78/-2 | 2 | DONE |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-logging` | 0.4 | +54/-1 | 2 | DONE |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-add-validate-` | 0.4 | +50/-1 | 2 | DONE |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-create-tests` | 0.4 | +42/-0 | 2 | DONE |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-define-valida` | 0.4 | +50/-0 | 1 | DONE |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-setup-basic-c` | 0.4 | +50/-0 | 1 | DONE |
| `canary-gemini-25-canary-gemini-25-validate-add-validation-function-test-function` | 0.4 | +81/-0 | 2 | DONE |
| `canary-gemini-25-canary-gemini-25-validate-integrate-validation-and-exit-code-en` | 0.4 | +50/-0 | 1 | DONE |
| `canary-ollama-strong-20260730` | 0.4 | +1/-0 | 1 | DONE |
| `copyfix-beethoven-07180848-slice-3-public-landing-founder-navigation-copy` | 0.4 | +1/-1 | 1 | QUARANTINED |
| `improve-automate-branch-management-slice-3` | 0.4 | +61/-0 | 1 | DONE |
| `backlog-batch-beethoven-22ee5bc-convention-conformance-lints-implement-task-test` | 0.3 | +37/-5 | 2 | DONE |
| `canary-gemini-25-canary-gemini-25-setup-create-requirements-file` | 0.3 | +3/-0 | 1 | DONE |
| `improve-missing-branch-auto-creator-slice-3-connect-event-to-branch-creation` | 0.3 | +127/-1 | 2 | DONE |
| `merged-diff-memory` | 0.3 | +343/-4 | 2 | DONE |
| `perpetual-compliance-hedge-instrument-fix-ts-errors-and-run-tests-fix-typescript` | 0.3 | +71/-68 | 30 | SUPERSEDED |
| `pinned-express-lane` | 0.3 | +73/-13 | 1 | DONE |
| `prompt-evolution-bandit` | 0.3 | +17/-4 | 1 | DONE |
| `relfix-vercel-checks-cache-transplant-relfix-vercel-checks-patch` | 0.3 | +35/-1 | 2 | DONE |
| `copyfix-beethoven-07180848-slice-3-public-landing-portfolio-objectives-copy` | 0.2 | +1/-1 | 1 | QUEUED |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-1` | 0.2 | +633/-3 | 4 | MERGED |
| `dropbox-beethoven-audit-addendum-two-session-recon-slice-2` | 0.2 | +676/-8 | 4 | MERGED |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-1` | 0.2 | +1259/-3 | 6 | MERGED |
| `improve-missing-branch-auto-creator-slice-3-locate-decomposition-event-handler-a` | 0.2 | +727/-2 | 5 | QUEUED |
| `improve-missing-branch-auto-creator-slice-3-locate-decomposition-handler` | 0.2 | +630/-0 | 3 | DONE |
| `improve-missing-branch-auto-creator-slice-3-integrate-and-test` | 0.1 | +4/-0 | 1 | QUEUED |
| `improve-missing-branch-auto-creator-slice-3-run-tests` | 0.1 | +4/-0 | 1 | DONE |
| `improve-missing-branch-auto-creator-slice-3-update-task-decomposition` | 0.1 | +4/-0 | 1 | DONE |
| `improve-missing-branch-auto-creator-slice-3-write-tests` | 0.1 | +4/-0 | 1 | DONE |
| `dropbox-beethoven-audit-addendum-two-session-reconciliation-read-wit-group-4` | 0.0 | +481/-4 | 3 | QUEUED |
| `dropbox-beethoven-core-integrity-audit-merge-safety-self-protection--group-1` | 0.0 | +310/-9 | 2 | QUEUED |
| `dropbox-beethoven-fleet-immune-system-throughput-a-slice-1` | 0.0 | +769/-3 | 5 | TESTFAIL |
| `dropbox-beethoven-fleet-immune-system-throughput-a-slice-2` | 0.0 | +185/-12 | 2 | QUEUED |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-1` | 0.0 | +254/-27 | 3 | QUEUED |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2` | 0.0 | +230/-156 | 2 | RUNNING |
| `dropbox-hisanta-mastery-engine-grandma-rail-family-slice-3` | 0.0 | +256/-157 | 3 | QUEUED |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-batch-fusion-unpause` | 0.0 | +300/-12 | 2 | RUNNING |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-billing-guard-scope` | 0.0 | +487/-94 | 2 | QUEUED |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-bulk-integrate-shelf` | 0.0 | +418/-0 | 2 | QUEUED |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-db-env-loader-guard` | 0.0 | +247/-7 | 3 | DECOMPOSED |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-governor-ram-floor` | 0.0 | +197/-5 | 2 | QUEUED |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-hermetic-worktree-preflight` | 0.0 | +487/-0 | 2 | DONE |
| `dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-keepalive-single-supervisor` | 0.0 | +436/-7 | 3 | QUEUED |
| `dropbox-recover-the-lease-night-stash-work-branch-hotfix-stash-rescu-group-1` | 0.0 | +401/-0 | 4 | QUEUED |
| `dropbox-wave-c-compounding-codegen-platform-spine--slice-3` | 0.0 | +721/-5 | 4 | RUNNING |
| `fleet-stale-host-server-side-guard-cowork-20260806` | 0.0 | +585/-0 | 3 | DONE |
| `no-done-without-evidence-cowork-20260806` | 0.0 | +369/-1 | 3 | DONE |
| `relfix-release-hold-deadlock-cowork-20260806` | 0.0 | +268/-5 | 4 | DONE |
| `triage-route-by-executor-reliability-shadow-cowork-20260806` | 0.0 | +613/-0 | 4 | DONE |

## Branches that would conflict

| branch | age (d) | src +/- | files | class | task state |
|---|---:|---:|---:|---|---|
| `convention-conformance-lints` | 33.9 | +222/-2 | 4 | unclear | SUPERSEDED |
| `orch-cross-project-depends` | 22.0 | +120/-10 | 5 | unclear | QUEUED |
| `qafix-beethoven-07230101` | 14.7 | +4/-0 | 1 | unclear | MERGED |
| `v15-fractal-runtime` | 11.1 | +5087/-11 | 44 | unclear | — no task row — |
| `dropbox-apparently-merge-vigil-into-apparently-gaming-exams-for-all--master-task` | 9.4 | +4/-0 | 1 | unclear | DECOMPOSED |
| `canary-codex-17` | 7.2 | +2/-3 | 2 | unclear | QUARANTINED |
| `canary-codex-34` | 6.6 | +32/-2 | 3 | unclear | QUARANTINED |
| `canary-codex-39` | 6.5 | +74/-12 | 5 | unclear | QUARANTINED |
| `canary-codex-46` | 5.7 | +61/-0 | 3 | unclear | DECOMPOSED |
| `qafix-beethoven-08010307` | 4.7 | +28/-0 | 1 | unclear | QUARANTINED |
| `backlog-batch-beethoven-d00ef24` | 4.6 | +13/-0 | 4 | unclear | DECOMPOSED |
| `canary-claude-27-slice-1` | 4.6 | +4191/-2 | 9 | unclear | DECOMPOSED |
| `improve-missing-branch-auto-creator-slice-3-finalize-build-and-config` | 0.8 | +133/-1299 | 11 | unclear | QUEUED |
| `improve-missing-branch-auto-creator-slice-3-fix-base-branch-detection` | 0.8 | +133/-1299 | 11 | unclear | DONE |
| `backlog-batch-beethoven-7c38d4c` | 0.4 | +6/-2 | 1 | unclear | DONE |
| `backlog-batch-beethoven-e63dfee-apply-economic-scheduler-revenue-patch-build-and` | 0.4 | +23/-2 | 2 | unclear | DONE |
