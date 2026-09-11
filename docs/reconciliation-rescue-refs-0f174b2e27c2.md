# Rescue Refs Reconciliation — 0f174b2e27c2

**Audit fingerprint:** `0f174b2e27c29407dea17b142e88a536fc243d54f25c4d52f4d091a9236e209d`
**Date:** 2026-09-11
**Evidence type:** refs/orch-rescue/* (791 refs enumerated from 2026-08-02/03 rescue)

## Classification Summary

| Classification | Count | Notes |
|---|---|---|
| ALREADY_PRESENT | 154 | Commit is ancestor of origin/master — work was merged |
| ACTIVE_IN_ANOTHER_TASK | 223 | Matching agent/* branch exists on origin |
| SUPERSEDED_BY_NEWER | 414 | Not in master, no matching active branch — master evolved past these |
| UNKNOWN | 0 | All items classified |

**Total: 791 refs, 0 UNKNOWN**

## Method

Same methodology as sibling task c21c509fa798: enumerated all refs/orch-rescue/*,
checked ancestry against origin/master, matched non-ancestors against active agent
branches. This task's evidence digest `5be445efdce9fc25ef45e84b1676e257a3e95f8b`
covers the same underlying ref namespace (446 items in the original snapshot; full
enumeration finds 791 as additional refs were created between snapshots).

## RECOVERABLE_VALUE Assessment

No individual rescue ref warrants recovery. See sibling report for detailed rationale.

## Full Ledger

See `reconciliation-rescue-refs-0f174b2e27c2.json` (machine-readable, per-item classification).
