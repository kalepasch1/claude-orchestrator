# MISSION: Complete, merge, and deploy the full backlog to Vercel TODAY — then make the fleet permanently faster

You are working in `~/Documents/beethoven/claude-orchestrator` (Mac 1, the fleet primary). Work in phase order — each phase gates the next. Commit per phase with `git commit --no-verify`, push to origin, and propagate to Mac 2 via `fleet_control` rows (never manual SSH). Follow repo conventions: ORCH_-prefixed config keys, no secrets in config or code, fail-soft error handling (return defaults, never wedge the runner), 20+ test cases for any new module.

## GROUND TRUTH (verified by log forensics — do not re-litigate)

- The global kill switch has been PAUSED since ~01:15 last night. Cause: `runner/.env` line 9 has an active `ANTHROPIC_API_KEY`; `runner/db.py` re-loads `.env` with `os.environ.setdefault()` on import, re-injecting the key into every periodic subprocess AFTER `subscription_guard.enforce()` strips it at startup. `billing_guard` (runs via `periodic.py`, which does `import db`) sees the key, trips, and re-pauses globally every 5 minutes — 878 consecutive trips. Any manual resume is undone within 5 minutes until the root cause is fixed.
- Multiple keepalive supervisors are racing since ~10:13 (runner starts ~1/second in `.runtime/logs/runner.log`).
- Queue state: ~1,161 queued / 0 running; ~69 recovery tasks, ~93 release-fix tasks, ~71 improvement tasks; 49 recent failed releases; total ~3,562 tasks.
- Last night's few claimed tasks failed to merge: "build RED → not merging" (npm toolchain missing in worktrees), `[artifacts] DB store failed: HTTP 404`, canonical merge train HTTP 500 → legacy fallback.
- `merge_train`, `improve`, `batch_fusion`, `deployverify`, `releasetrain` all sat paused/skipped overnight. `drain_mode=true`. Resource governor clamps to 2–3 lanes (6GB RAM floor).

## PHASE 0 — UNBLOCK THE FLEET (do first, nothing works until this is done)

1. In `runner/.env`: comment out the active `ANTHROPIC_API_KEY` line. Keep a note pointing to ORCH_ALLOW_API_BILLING for deliberate opt-in.
2. Patch `runner/db.py` env loader: never inject `ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY_*` via setdefault unless `subscription_guard.is_api_allowed()` is true. Fail-soft if subscription_guard can't import (default: do NOT inject).
3. Kill all keepalive supervisors and stale locks; start exactly one:
   `pkill -f keepalive.sh; pkill -f runner.py; rm -f .runtime/runner.lock; rm -rf .runtime/keepalive.lock*; (cd runner && nohup bash keepalive.sh &)`
4. Resume: `python3 runner/kill_switch.py resume`. Verify billing_guard logs `clean` on its next two cycles and `merge_train` no longer logs `paused — skipping`.
5. Patch `billing_guard.py`: when a previous trip's cause is no longer present, it RESUMES its own pause (scope its pauses with `by="billing_guard"` and only auto-resume those). Add: after 3 identical consecutive trips, escalate one material approval instead of re-tripping silently forever.

**Acceptance:** `autopilot_state.json` snapshots show running > 0 within 15 minutes; billing_guard clean; single keepalive PID.

## PHASE 1 — QUEUE BANKRUPTCY (shrink 1,161 to the real core)

6. Write `runner/queue_bankruptcy.py` (idempotent, dry-run flag): dedupe queued tasks by fingerprint (project + normalized title/prompt); close `recover-missing-branch-*` tasks whose branch is already merged into master or no longer exists; close release-fix tasks whose target build is currently green; close tasks older than 14 days with no claim. Record every closure with a reason in the task row. Run it with `--dry-run`, review counts, then live.
7. Un-pause `batch_fusion` and fuse remaining small same-repo mechanical tasks into batches of 5–10 per session.
8. Keep drain_mode ON for all speculative generators (colosseum, cade_tournaments, agent_market, committees, bot factory, business_radar) for 24h. Add config key `ORCH_META_PRODUCT_RATIO_CAP` (default 0.5) enforced at task insert: meta-work (recovery/release-fix/improve) may never exceed the cap vs product work.

**Acceptance:** queued count reduced ≥60% with audit trail; no new speculative tasks appear for 24h.

## PHASE 2 — FIX THE MERGE PIPELINE (where last night actually died)

9. Hermetic worktree toolchain: add a per-project preflight that runs once per project per day — verify node/npm present, run `npm ci` in a shared per-project cache, symlink or copy `node_modules` into each new worktree. A task may NOT be claimed for a project whose preflight is red; mark the project blocked with reason instead of burning a model run and failing the build.
10. Fix `[artifacts] DB store failed: HTTP 404`: either create the missing Supabase table/endpoint (add migration) or remove the write path. No fail-soft swallowing here — artifacts must store or the code must not try.
11. Fix the canonical merge train HTTP 500 → find the failing endpoint call, correct it, and make legacy fallback log loudly with the underlying error.
12. Bulk-integrate shelf inventory: enumerate all `agent/*` branches ahead of master whose agent run already committed work; for each, build + verify + merge directly via the existing `integrate-existing` path — no agent re-run. Order by rebase-stack (related branches sequentially) to avoid conflict storms.

**Acceptance:** first-pass merge rate > 70% on the next 20 integrations; zero "npm not installed" build REDs; artifacts writes succeed.

## PHASE 3 — MAXIMUM SAFE THROUGHPUT TODAY

13. Governor: lower RAM floor to 4GB via `ORCH_` config (fleet-wide through `fleet_config`), target 6–8 lanes on Mac 1. Confirm Mac 2 is on current code via `fleet_control` git_pull + restart rows; it doubles lane count.
14. Routing: subscription lanes (all 3 accounts healthy since the 6 AM reset) for judgment-heavy tasks; aider/DeepSeek/Gemini cheap lanes for fused mechanical batches. Never inject Anthropic API keys — subscription only unless ORCH_ALLOW_API_BILLING is deliberately set.
15. Context diet: stop reading/writing the 13.8MB `.orch-context-cache.json` as task context. Generate a distilled per-project brief (≤4KB) and use the stable cached prefix (`caching.py`) for everything else. Remove `.orch-context-cache.json` from git tracking (add to `.gitignore`).

**Acceptance:** ≥6 concurrent lanes sustained; cost telemetry shows cheap lanes handling mechanical batches; per-task input tokens down materially.

## PHASE 4 — DEPLOY TO VERCEL TODAY

16. Re-enable `releasetrain` and `deployverify`. Wire deploy: on merge-train success for `web/`, trigger the Vercel deploy hook (store hook URL as env var, not in code), wait for the preview URL, run a smoke test (page loads, auth redirect works, tasks board renders), then promote to production. Rollback on smoke failure.
17. Add a deploy KPI row after every deploy attempt: merged count today, first-pass rate, deploy status, paused-minutes today. Surface on the dashboard.

**Acceptance:** production Vercel deployment today from the merged backlog, with a green smoke test recorded.

## PHASE 5 — PERMANENT SELF-IMPROVEMENT (quality + speed compounding)

18. Pause-arbiter: consolidate all `kill_switch.pause` callers behind one arbiter with typed reasons, TTLs, auto-resume-when-cause-clears, and max-3-identical-trips-then-escalate. Guards register causes; the arbiter owns the switch.
19. Watchdog SLO: new periodic job — if `queued>0 ∧ running==0` for 15+ minutes, auto-diagnose (billing? limits? locks? governor?), attempt remediation, and file one loud notification. Last night was visible in data by 01:30 and nobody was told.
20. Interlock tests in CI (add to the standard test run): (a) import `runner/db.py` in a clean env with a dummy key in `.env` fixture → assert no `ANTHROPIC_API_KEY` in `os.environ` when billing blocked; (b) kill_switch pause→resume round-trip wins over older rows; (c) billing_guard trip→auto-resume when cause cleared. 20+ cases across the three.
21. Structured logging: every log line from runner + periodic jobs gets an ISO timestamp and job name (JSONL where cheap). No new logger frameworks — extend the existing print paths.
22. Eval-gated self-improvement: each merged `improve`-lane change must declare its target KPI (merged/day, first-pass rate, paused-minutes, $/task). `eval_harness.py` compares 24h before/after; if the KPI didn't move, auto-file a revert proposal. Self-improvement is measured by outcomes, not activity.

**Acceptance:** all tests green in CI; arbiter is the only writer to `controls`; a self-improvement merged this week shows its KPI delta.

## GUARDRAILS

- Never commit secrets. Never re-enable API billing implicitly. All fleet config via `fleet_config` with ORCH_ keys.
- Material/risky changes (schema, deploy wiring, governor floor) go through an approval card as usual — but batch them into ONE card per phase, not 20.
- If blocked > 20 minutes on any item, file the blocker, skip, and continue the phase — do not wedge.
- End of day: write `REPORT-backlog-blitz.md` — tasks closed vs merged vs deployed, KPI deltas, and the top 3 remaining bottlenecks.

## ADDENDUM — ALIGN WITH THE ORCHESTRATOR'S OWN EXECUTION MODEL

This manual Claude Code session is the BOOTSTRAP exception (the fleet was dead). Do not execute Phases 3–5 serially yourself. Once Phase 0 and Phase 2 acceptance criteria pass:
- Decompose every remaining item into the canonical intake format and drop as `intake/backlog-blitz-<phase>.md` (PROJECT, id, title, material, model, depends, proof, prompt). `intake_watcher.py` will queue them dependency-linked and model-routed; the fleet executes them in parallel and records outcomes/knowledge.
- Keep only fleet-down remediations (anything that must run while the runner is broken) in this session.
- Verify intake_watcher is unpaused and processed your drops before ending the session.
