# Stash Reconciliation Report — 23dc7a68bc61

**Audit fingerprint:** `23dc7a68bc61eaf9b564e7b07720667f0c347d198c00ee284875ebafa0f4f34b`
**Date:** 2026-09-11
**Evidence type:** git stash entries (13 items enumerated)

## Classifications

| Stash | SHA (short) | Subject | Classification | Rationale |
|-------|-------------|---------|----------------|-----------|
| stash@{0} | 793e4b527273 | WIP: stop thirteen unit tests from walking home dir | RECOVERABLE_VALUE | Fixes split() maxsplit in autoclear_policy.py + adds autoclear_rules.yaml policies. 0 commits touch these files since parent. Changes not in master. Applied in this branch. |
| stash@{1} | 67d82ea9d929 | other agent's work, set aside for 65a2caba promotion | RECOVERABLE_VALUE | Input validation for counterfactual_replay.py + 1733 lines of new tests. 0 commits touch these files since parent. Applied in this branch. |
| stash@{2} | f5d33f4a1334 | foreign: test_diagnostic_missing_branch.py (set aside for e1e0d174) | ALREADY_PRESENT | Empty diff — no file changes in stash. Nothing to recover. |
| stash@{3} | 12f9e378c343 | other agent's work, set aside for f9ffdc45 promotion | SUPERSEDED_BY_NEWER | Identical file set to stash@{1}. stash@{1} is the canonical copy. |
| stash@{4} | 2ba3d61789e5 | WIP: chatgpt-local-reconcile merge | ACTIVE_IN_ANOTHER_TASK | Has rescue branch origin/hotfix/stash-rescue-1788624760-2ba3d617. hisanta contracts + periodic.py. |
| stash@{5} | 97156da4105c | WIP: canary-deepseek-1-conftest-restore | SUPERSEDED_BY_NEWER | conftest module isolation tests. 2 commits touched these files since; master has evolved. |
| stash@{6} | d9cf03a32ca3 | WIP: human-decision-git-lock | SUPERSEDED_BY_NEWER | 26-file changeset. Has rescue branch. 5 commits touched files since. Parent not in master. |
| stash@{7} | fabf9fe23d45 | WIP: canary-deepseek-1 | SUPERSEDED_BY_NEWER | conftest.py rewrite. 6 commits touched file since. Parent not in master. |
| stash@{8} | baedc106cce6 | strays-2159 | SUPERSEDED_BY_NEWER | resource_governor.py additions. 3 commits touched file since. Parent not in master. |
| stash@{9} | 738179e46f91 | strays-20260901-2140 | SUPERSEDED_BY_NEWER | fleet_control.py additions. 5 commits touched files since. Parent not in master. |
| stash@{10} | 80740fe5fd5f | WIP: resource_governor env-var reads | SUPERSEDED_BY_NEWER | 137-file cleanup. Has rescue branch. 9 commits touched files since. |
| stash@{11} | a9f38fd798b8 | WIP: opportunity_scout tests | SUPERSEDED_BY_NEWER | 49 commits touched files since. Has rescue branch. Heavily superseded. |
| stash@{12} | 6ca51b977b01 | WIP: cost intelligence docs | SUPERSEDED_BY_NEWER | Recovery ledger docs. Has rescue branch. 4 commits touched files since. |

## Summary

- **RECOVERABLE_VALUE:** 2 (stash@{0}, stash@{1}) — applied in this branch
- **ALREADY_PRESENT:** 1 (stash@{2})
- **SUPERSEDED_BY_NEWER:** 8 (stash@{3,5,6,7,8,9,10,11,12})
- **ACTIVE_IN_ANOTHER_TASK:** 1 (stash@{4})
- **UNKNOWN:** 0
