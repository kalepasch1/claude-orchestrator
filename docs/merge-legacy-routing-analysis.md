# Merge Analysis: agent/rework-legal-rework-legal-provider-parallel-rate-aware-routing-c15df85-06f75d6

**Date:** 2026-07-16
**Branch:** `origin/agent/rework-legal-rework-legal-provider-parallel-rate-aware-routing-c15df85-06f75d6`
**Target:** `origin/master`
**Merge-base:** `45fc73ca` (fix: fleet-aware agent branches)

## Summary

The branch contains 6 commits (on top of merge-base `45fc73c`), totaling 14 files changed
(+1317/-48 vs merge-base). **5 of 6 commits have already been cherry-picked or independently
re-landed on master.** Only the `provider_rate_router` commit remains unmerged.

## Commit-by-commit status

| # | Commit (branch) | Summary | On master? | Master commit |
|---|-----------------|---------|------------|---------------|
| 1 | `bc1bc00` | Add end-of-session reports (REPORT-*.md) | YES | `16c4cdd`, `7ff21af` |
| 2 | `5c3a416` | queue_elimination: isolated worktree safety | YES | `de9e4d3` |
| 3 | `10972df` | deploy_window: isolated worktree safety | YES | `9a1a623` |
| 4 | `3e65e16` | approval_merge/runner: isolated rebase worktree | YES | `9383ee6` |
| 5 | `98ff235` | intake_watcher: claim dropbox before decomposing | YES | `2dec594` |
| 6 | `223903b` | provider_rate_router: proactive rate-aware routing | **NO** | -- |

## Unmerged: provider_rate_router (commit 223903b)

### New files (not on master)
- `runner/provider_rate_router.py` (173 lines) -- proactive rate-aware account routing
- `runner/tests/test_provider_rate_router.py` (175 lines) -- full test suite

### What provider_rate_router does
- Adds a `pick(task_slug)` function that selects the best provider account for parallel dispatch
- Ranks healthy accounts by (not cooling down, then remaining tokens descending)
- Supports `ORCH_FORCE_ACCOUNT` env override for operator pinning
- Logs routing decisions to `provider_routing_log.jsonl` for audit
- No secrets handled -- delegates credential injection to `account_pool.env_for()`

### Integration point
- `runner/runner.py` is NOT modified to import/use `provider_rate_router` in this branch
- The module is standalone and additive -- no existing code is changed for it
- It would need to be wired into the dispatch path in runner.py to take effect

## Recommendation

**Status: PARTIALLY MERGED -- one additive module remaining.**

The 5 already-merged commits cover the critical worktree-safety and intake-ordering fixes.
The remaining `provider_rate_router` module is additive (new files only, no modifications to
existing code) and not yet wired into the runner dispatch path.

Options:
1. **Cherry-pick commit `223903b`** to land the rate router module on master. Low risk --
   purely additive, no conflicts expected. Wire it into runner.py separately.
2. **Close the branch as substantially merged.** The rate router can be re-implemented when
   the dispatch path is ready for it -- the module is self-contained.

The branch should NOT be merged as a whole (full `git merge`) because it is 622 files behind
master and would create a massive, misleading merge commit.
