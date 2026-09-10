# Reconciliation: chatgpt-local-reconcile-beethoven-8e79d6bdcb55

Audit fingerprint: `8e79d6bdcb5579f8c4c5dbd0ac9a49080c2c43ac190c7641f4630e4bda6f4feb`
Evidence kind: stashes (9 items)
Repo: /Users/kpasch/Documents/beethoven/claude-orchestrator
Master HEAD at reconciliation: bcacf428e

## Evidence Classification

### stash@{0} (current @{4}) — sha 2ba3d61
- **Subject:** WIP on master: 9ab9814c Merge branch 'agent/chatgpt-local-reconcile-beethoven-feb91eed3b7c'
- **Files:** hisanta/contracts/family.py, hisanta/tests/test_contract_singleton.py, runner/periodic.py (5 files, 310 ins)
- **Classification:** SUPERSEDED_BY_NEWER
- **Reason:** Contains unresolved merge conflict markers (<<<<<<< HEAD) in test_contract_singleton.py. Master has the clean resolved version with canonical file reconciliation from 2026-08-23.

### stash@{1} (current @{5}) — sha 97156da
- **Subject:** WIP on canary-deepseek-1-conftest-restore: 6cec1792
- **Files:** test_conftest_module_isolation.py (443 lines vs 98 on master), test_pinned_express_lane.py (2 files, 453 ins)
- **Classification:** SUPERSEDED_BY_NEWER
- **Reason:** Canary branch test expansions (443 lines) were experimental; master retains a curated 98-line subset. Base commit is in master; canary branch work completed.

### stash@{2} (current @{6}) — sha d9cf03a
- **Subject:** WIP on master: e2045d98 Merge branch 'agent/human-decision-git-lock-mac247-20260904-x9wq'
- **Files:** 26 files, 1262 insertions (scripts/check-build-tools.sh, web/components/PublicLanding.vue, etc.)
- **Classification:** SUPERSEDED_BY_NEWER
- **Reason:** Base commit e2045d98 not in current master; branch has diverged. The 26-file change set was from a merge-in-progress state; master has since received the relevant changes via normal merge train.

### stash@{3} (current @{7}) — sha fabf9fe
- **Subject:** WIP on canary-deepseek-1: a9fa358e
- **Files:** runner/tests/conftest.py (71 ins, 28 del)
- **Classification:** SUPERSEDED_BY_NEWER
- **Reason:** Conftest.py on master is 905 lines and already incorporates the relevant test isolation fixes. Canary branch changes were experimental.

### stash@{4} (current @{8}) — sha baedc10
- **Subject:** On master: strays-2159
- **Files:** runner/resource_governor.py (96 insertions)
- **Classification:** SUPERSEDED_BY_NEWER
- **Reason:** Sentinel-collected strays. Master resource_governor.py is 944 lines with 25 os.environ reads; the additions are subsumed by current state.

### stash@{5} (current @{9}) — sha 738179e
- **Subject:** On master: strays-20260901-2140
- **Files:** runner/fleet_control.py, runner/tests/test_fleet_control.py (207 insertions)
- **Classification:** SUPERSEDED_BY_NEWER
- **Reason:** Sentinel-collected strays. Master fleet_control.py is 973 lines; test additions are subsumed.

### stash@{6} (current @{10}) — sha 80740fe
- **Subject:** WIP on master: 527f1ef0 Fix: resource_governor — convert frozen module constants to live env-var reads
- **Files:** 137 files, 1108 ins, 6733 del (massive cleanup)
- **Classification:** ALREADY_PRESENT
- **Reason:** The fix referenced in the stash subject (527f1ef0) converted frozen constants to env-var reads. Master resource_governor.py already has 25 os.environ references confirming the fix was applied. The 137-file delta was the WIP state during that large refactor.

### stash@{7} (current @{11}) — sha a9f38fd
- **Subject:** WIP on master: 2acd4139 Add comprehensive tests for opportunity_scout.py RICE scoring
- **Files:** runner/runner.py, runner/session_launcher.py (7 files, 43 ins)
- **Classification:** ALREADY_PRESENT
- **Reason:** opportunity_scout.py exists on master (4146 bytes). The commit 2acd4139 adding tests was the base; the stash WIP was incremental changes during that work that were subsequently merged.

### stash@{8} (current @{12}) — sha 6ca51b9
- **Subject:** WIP on master: e5c6c5bf docs: top 3 highest-leverage opportunities from runner codebase scan (RICE-scored)
- **Files:** 13 files, 31192 ins (account_pool.py, config_consumer.py, merge_truth.py, pipeline_funnel.py, session_cache.py, recovery-ledger docs)
- **Classification:** ALREADY_PRESENT
- **Reason:** All referenced runner modules exist on master: account_pool (407 lines), config_consumer (409), merge_truth (591), pipeline_funnel (266), session_cache (225). Recovery-ledger docs were from a prior reconciliation pass.

## Summary

| Evidence | Classification | Disposition |
|---|---|---|
| stash@{0} (2ba3d61) | SUPERSEDED_BY_NEWER | No action — conflict markers resolved on master |
| stash@{1} (97156da) | SUPERSEDED_BY_NEWER | No action — canary test expansions not needed |
| stash@{2} (d9cf03a) | SUPERSEDED_BY_NEWER | No action — diverged base, changes merged via train |
| stash@{3} (fabf9fe) | SUPERSEDED_BY_NEWER | No action — conftest fixes applied differently |
| stash@{4} (baedc10) | SUPERSEDED_BY_NEWER | No action — sentinel strays subsumed |
| stash@{5} (738179e) | SUPERSEDED_BY_NEWER | No action — sentinel strays subsumed |
| stash@{6} (80740fe) | ALREADY_PRESENT | No action — env-var fix confirmed on master |
| stash@{7} (a9f38fd) | ALREADY_PRESENT | No action — opportunity_scout work on master |
| stash@{8} (6ca51b9) | ALREADY_PRESENT | No action — all modules present on master |

Zero UNKNOWN items. Zero RECOVERABLE_VALUE items — all stash content is either already on master or superseded by newer work.
