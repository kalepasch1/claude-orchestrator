# Recover the lease-night stash work (branch: hotfix/stash-rescue-lease-night-5f879035)

Operator directive 2026-07-30. The stash-audit found ~78 substantive unrecovered lines from the
2026-07-29 lease-RPC night, swept by the (now root-cause-fixed) anonymous-stash bug. The work is
preserved on branch `hotfix/stash-rescue-lease-night-5f879035` (also `hotfix/stash-rescue-1785390774-5f879035`,
same commit). Recover it PROPERLY — re-apply onto current master with judgment, not a blind patch.

## What the branch contains (verified by containment analysis)
1. `runner/db.py` — `CORE_RETRY_RPCS` allowlist: retry-with-backoff for transient failures on the
   core RPCs (`acquire/heartbeat/release_branch_execution_lease`, `execute_task`, `complete_task`,
   `claim_task`, `mark_done`, `record_attempt`, `update_task_state`, `insert_outcome`). This is the
   resilience hardening for exactly the outage class that mass-quarantined 91 tasks that night.
2. `runner/pipeline_contract.py` (~94 lines) — security/legal task gating: `LEGAL_RX` classifier,
   `ORCH_SECURITY_TASK_ALLOWLIST` / `ORCH_LEGAL_TASK_ALLOWLIST` env allowlists,
   `RESTRICTED_OPERATIONS`, `_credential_allows`, `_operation_authorized`.
3. `runner/merge_train.py` (13 lines) + `runner/deployment_bindings.json` +
   `scripts/fleet_config_baseline.json` — small consistency updates; verify against current state
   before applying (these files have moved substantially since).
4. `CLAUDE.md` auto-conventions hunk — LOW value; skip unless trivially clean.

## Requirements
- Work in a worktree per convention; never touch the main checkout.
- 3-way merge each hunk against CURRENT master; where the codebase has since evolved a different
  solution for the same problem, prefer current and note the divergence rather than forcing.
- Tests for the db.py retry behavior (transient failure → retried; permanent → surfaced) and for
  the pipeline_contract gates (allowlisted passes, non-allowlisted restricted op blocked).
- Do NOT delete the rescue branches; they are the provenance record.
