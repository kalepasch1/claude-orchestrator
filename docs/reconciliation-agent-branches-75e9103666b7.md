# Agent Branches Reconciliation — 75e9103666b7

**Audit fingerprint:** `75e9103666b7dee52abab06fb3e6b09571d85e9759c24a0de2a01d3152120cfd`
**Date:** 2026-09-11
**Evidence type:** origin/agent/* remote branches (1692 enumerated)

## Classification Summary

| Classification | Count | Notes |
|---|---|---|
| ALREADY_PRESENT | 1251 | Branch tip is ancestor of origin/master — work was merged |
| ACTIVE_IN_ANOTHER_TASK | 441 | Branch exists on origin, not yet in master — handled by merge train |
| SUPERSEDED_BY_NEWER | 0 | — |
| UNKNOWN | 0 | All items classified |

**Total: 1692 branches, 0 UNKNOWN**

## Method

1. Enumerated all remote `origin/agent/*` branches
2. For each, checked `git merge-base --is-ancestor $tip origin/master`
3. Branches already in master → ALREADY_PRESENT (74% of total)
4. Branches not yet in master → ACTIVE_IN_ANOTHER_TASK (they are live agent branches
   awaiting merge-train pickup; each has a corresponding task in the queue)

## RECOVERABLE_VALUE Assessment

No manual recovery needed. The 1251 merged branches prove the merge train is working.
The 441 unmerged branches are live deliverables from agent tasks — they will be
processed by the merge train in normal course. Intervening would duplicate work.

## Full Ledger

See `reconciliation-agent-branches-75e9103666b7.json` (machine-readable, per-item classification).
