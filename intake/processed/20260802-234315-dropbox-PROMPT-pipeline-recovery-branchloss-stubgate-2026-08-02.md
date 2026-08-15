# beethoven: PIPELINE RECOVERY — missing-branch root cause + stub-merge gate + throughput SLO (operator directive 2026-08-02, HIGHEST PRIORITY)

SUBMITTED-BY: kale@smrter.us (operator) via Cowork recovery session 2026-08-02. Context: prod deploys are healthy but nearly no feature work reaches main. Since 07-28: tomorrow 312 QUEUED/3 MERGED, apparently 211/19, apparently-law 117/2, pareto 66/6. Sentinel showed train-stale ~2.4 days; SLO RED 0/5; merge train reports passed_waiting=0 with recurring missing_branch. Operator has already (today): merged stranded mac1-wip-2026-07-30 + -08-01 into master, restarted the fleet on reconciled code, kicked merge_train + release_train manually (both green), requeued 113 quarantined tasks, and set priority=1 on all QUEUED tasks for tomorrow/apparently/apparently-law/pareto-2080. This PROMPT is the durable fix for the three root causes that remain.

## 1. Missing-branch loss — find and kill the root cause (P0)
- Completed agent work repeatedly loses its branch before the train can promote it (recover-missing-branch-* tasks, train missing_branch counters, stranded-commit alerts). Instrument the full branch lifecycle: creation → commits → test pass → train pickup, logging every deletion/GC/prune/force-push with actor and timestamp. Identify the deleter (worktree GC? branch-lease expiry? cleanup sweeps? checkout_guard? vercel-branch hygiene?).
- Fix at the source: completed-but-unpromoted branches are IMMUNE from any GC/prune until the train records promotion or explicit closure; add a grace ledger. Backstop: on any branch loss, auto-materialize the recovery task immediately (not hours later) from the artifact/patch cache.
- Proof: zero new missing_branch occurrences across 48h of runs; synthetic test that GC cannot delete a passed-waiting branch.

## 2. Stub-merge gate — stop merging destructive "build stubs" (P0)
- Recent main commits are restorations of modules "replaced by build stubs" / "destroyed by auto-resolved merges" (tomorrow pricing/replication modules, ploeh schemas, pareto statistical modules). Some QA/merge path accepts diffs that replace real implementations with stubs, and some auto-resolution strategy destroys code.
- Add a hard merge gate: reject any diff that (a) reduces a module to a stub/no-op while callers remain, (b) deletes exported symbols still referenced, or (c) shrinks a file below a configurable fraction of its size without an explicit allow-tag. Wire into the same hook family as the regression guard; log every rejection with the offending task id so the routing/model that produced it gets downscored.
- Disable or constrain whatever auto-resolve merge strategy produced "auto-resolved merges" that destroyed modules — auto-resolution may never resolve by wholesale deletion.
- Proof: fixture stub-diff is rejected; fixture legitimate-refactor with allow-tag passes; auto-resolve cannot delete >N lines without escalation.

## 3. Throughput + backpressure (P1)
- The queue grew ~50-100x faster than it drained. Add an intake backpressure rule: when QUEUED exceeds a configurable ceiling per project, new intake decomposition parks in a staged state (visible, not lost) until the queue drains below the floor — never silently drop.
- Raise effective execution concurrency where resources allow (current throttle=10) with thermal/memory guards; report claimed-vs-completed per hour on the SLO dashboard; SLO must include "feature commits reaching prod branch per day per app" as a first-class metric (repairs tagged separately so restoration work cannot masquerade as feature throughput).
- Proof: SLO dashboard shows the new metric; synthetic flood test parks instead of ballooning the queue.

OPERATOR (logged, never queued):
- Review the 4 add/add conflict resolutions from the mac1-wip merge (kept master side: blocked_triage.py + 3 test files) — confirm nothing needed from the wip versions.
- Mac 2 was unreachable over SSH; a fleet_control git_pull+restart row was queued — verify Mac 2 picked it up.
