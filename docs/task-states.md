# Task State Machine Reference

Valid task states and transitions:

```
QUEUED ──→ RUNNING ──→ DONE
  │           │          │
  │           ├──→ BLOCKED (repo path missing)
  │           │
  │           └──→ QUARANTINED (binary-only stub)
  │
  └──→ (claimed by executor, state set to RUNNING)
```

- **QUEUED**: Ready for execution, waiting to be claimed
- **RUNNING**: Claimed by an executor, implementation in progress
- **DONE**: Successfully implemented, committed, and pushed
- **BLOCKED**: Cannot proceed (e.g., repo path does not exist)
- **QUARANTINED**: Invalid or malformed task (binary hex-only stubs)
- **MERGED**: Post-DONE state after merge train promotes the branch
