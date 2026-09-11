# Stash Reconciliation — 240b096c90a6

**Audit fingerprint:** `240b096c90a670f51bdce54df6a75070512deb43718ba09cd8553e3c048fc79f`
**Date:** 2026-09-11
**Evidence type:** git stash entries (13 items enumerated)

## Classification Summary

| Classification | Count |
|---|---|
| RECOVERABLE_VALUE | 2 (already applied in sibling task 23dc7a68bc61) |
| ALREADY_PRESENT | 1 |
| SUPERSEDED_BY_NEWER | 8 |
| ACTIVE_IN_ANOTHER_TASK | 1 |
| UNKNOWN | 0 |

**Total: 13 stash entries, 0 UNKNOWN**

The 2 RECOVERABLE_VALUE stashes (autoclear_policy fix + counterfactual_replay tests)
were already recovered and pushed in sibling task 23dc7a68bc61 (commit 0004639f6).

## Full Ledger
See `reconciliation-stash-240b096c90a6.json`
