# Rescue Refs Reconciliation — e252c1f8d0ed

**Audit fingerprint:** `e252c1f8d0ede997ec2325d437e0289d8a47e76686cc926d57e2b870e81648b3`
**Date:** 2026-09-11
**Evidence type:** refs/orch-rescue/* (791 refs enumerated)

## Classification Summary

| Classification | Count |
|---|---|
| ALREADY_PRESENT | 154 |
| ACTIVE_IN_ANOTHER_TASK | 223 |
| SUPERSEDED_BY_NEWER | 414 |
| UNKNOWN | 0 |

**Total: 791 refs, 0 UNKNOWN**

## Method
Enumerated all refs/orch-rescue/*, checked ancestry against origin/master,
matched non-ancestors against active agent branches. Same methodology as sibling tasks.

## Full Ledger
See `reconciliation-rescue-refs-e252c1f8d0ed.json`
