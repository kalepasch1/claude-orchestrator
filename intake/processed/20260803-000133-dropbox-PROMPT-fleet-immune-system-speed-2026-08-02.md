# beethoven: FLEET IMMUNE SYSTEM + THROUGHPUT ACCELERATORS (operator directive 2026-08-02, HIGHEST PRIORITY — runs with pipeline-recovery-branchloss-stubgate)

SUBMITTED-BY: kale@smrter.us (operator) via Cowork recovery session 2026-08-02. Diagnosis of record from today's incident: (1) 64 of 66 headless coder lanes were zombies >1h old — the fleet was "full of dead workers", pinning ALL RAM+slots; (2) legal_docket.py leaked 14 concurrent copies (8-10h old on a 30-min interval); (3) the runner mem-gate was correctly holding new claims due to RAM starvation CAUSED by (1)+(2) — claimable=803 while claiming ~0; (4) Mac 2's runner has been down since ~10:28 with no alert to the operator; (5) sentinel's train-stale was a false alarm for days (pressure written to DB, sentinel watching file — hotfixed a94f4bb4); (6) release train batch floor of 10 silently held small merges out of prod (hotfixed 04b55df6, RELEASE_MIN_BATCH=1 recovery mode active); (7) weak-coder routes produced "0/12 merged" cycles on legal-class tasks. A stopgap watchdog is live (runner/tools/lane_medic.sh). This PROMPT makes prevention and speed durable.

## 1. Never again: lane + daemon immune system (P0)
- HARD TIMEOUT on every agentic-coder invocation: wrap headless sessions with a per-task-class wall-clock limit (default 45m, config per class); on expiry kill the process tree, mark the task RETRY with note, and free the lane. A lane without a live heartbeat (progress file/stdout activity every N min) is killed earlier. This is the root-cause fix for zombie lanes — lane_medic.sh becomes a backstop, not the mechanism.
- SINGLE-INSTANCE LOCKS for all interval-scheduled scripts (legal_docket, expert_corps, benchmark_redlines, foulkon_sync, all [sched] entries): flock-style lock per script; a tick that finds the lock held logs and skips. Add a max-runtime kill inside each daemon (interval x1.5).
- Lane telemetry on the SLO dashboard: live lane count, age histogram, reaps/hour, mem-gate open/closed state and its RAM reading. Alert (operator ping via ops_alerts channel) when lanes>throttle+5 or mem-gate closed >15 min.
- Adopt lane_medic.sh logic into the scheduler proper, then keep the shell script as out-of-band backstop launched by keepalive.

## 2. Machine + pipeline heartbeat alerts (P0)
- Machine heartbeat table: each runner upserts a heartbeat every 5 min; a monitor alerts the operator (push/log/ops channel) when any machine is silent >30 min (Mac 2 was down half a day unnoticed). Include last-handled fleet_control row age.
- Pipeline consistency self-tests run hourly: pressure file mtime vs DB row (the bug class behind the false train-stale), sentinel boot-commit file written at runner start (fix the missing .runner_boot_commit warning), release-train env sanity (warn while RELEASE_MIN_BATCH=1 recovery mode active >72h).
- AUTO-REVERT: when a project's QUEUED count falls below 50 and stays there 24h, restore RELEASE_MIN_BATCH to default batching (remove the runner/.env override) and log the revert.

## 3. Speed: triage + routing accelerators (P0)
- Instrument stage-level cycle time per task: queued→claimed, claimed→coder-done, →QA, →merged, →released; publish p50/p90 per project + per model route on the SLO dashboard. "First-pass merge rate" per route is the headline metric.
- Route escalation: after 2 failed attempts on any task, force the strongest coder route (claude top-tier) regardless of qpd cost score; legal-class (need>=8) tasks NEVER route to weak local models for the coder stage (triage/QA may stay cheap). The observed "0/12 merged" haiku/ollama cycles on legal-class work burn lanes and days.
- Preflight triage health check: verify the triage stage is actually running and its classifications correlate with outcomes; publish triage accuracy (predicted class vs realized failure stage). Fix pattern_transfer auto_transfer_scan HTTP 404 (runner.log, recurring).
- Worktree hygiene: worktree_gc reports 98 skipped in-use/young/locked slots for smarter — audit locks, reclaim aggressively when the owning task is terminal; remove the dead /tmp/smoke-test-repo sweep error.
- RAM diet for speed: cap ollama keep_alive, prefer <=8B local models while total RAM headroom <8GB, and surface per-lane RSS so the governor can prefer many small lanes over few huge ones.

## PROOFS
- Kill -STOP a fixture lane: reaped by timeout within limit+2m and task requeued. Launch legal_docket twice: second exits on lock. Silence a machine heartbeat: operator alert fires. Delete pressure file: consistency test flags within 1h. Drain fixture project below threshold: auto-revert restores batching. Stage-cycle dashboard live with route win rates; 2-failure escalation observably reroutes; no legal-class coder runs on local small models (query proof).

OPERATOR (logged, never queued):
- Restart Mac 2 (command already provided in chat); enable Remote Login + install SSH key for future remote recovery.
- Keep the Mac unloaded tonight; review lane_medic.log tomorrow for reap counts (should trend to zero as §1 lands).
