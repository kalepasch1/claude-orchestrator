# Handoff prompt v3.2 — paste into Claude Code to finish the new layer

> I (Cowork) implemented goal-driven autonomy, portfolio health + action-inbox views,
> scoped-context retrieval, a result cache, fix-propagation, an opportunity scout, a prod
> watchdog, skill recipes, and a daily digest — all in `runner/` and wired into
> `runner.py`. They compile and import clean. The live Supabase is ALREADY migrated to
> 0003 (goals, result_cache, v_project_health, v_action_inbox). Your job: wire these into
> the UI, schedule them, and add the infra-heavy upgrades I can't do from here.

```
Continue the Claude Orchestrator in this repo. The runner already has these NEW modules
(all import-clean): goals.py, health.py, digest.py, context_retrieval.py, result_cache.py,
fix_propagation.py, opportunity_scout.py, watchdog.py, recipes.py (+ runner/recipes/*.md).
The live Supabase (ref eatfwdzfurujcuwlhdgj) is already at migration 0003. Do the following,
in order, in small verified steps. Never commit secrets; run builds/tests; report a checklist.

1. SMOKE-TEST the new modules against the live DB (export SUPABASE_URL + SERVICE key first):
   - `python3 runner/health.py`        (expect a JSON summary incl. tomorrow score 75)
   - `python3 runner/digest.py`        (prints/sends the digest)
   - Insert a test goal, run `python3 runner/goals.py`, confirm it queues tasks, then delete.
   Fix anything that errors against the real schema.

2. DASHBOARD: surface the new data in web/pages/index.vue (and keep it building):
   - A "Portfolio" section reading `v_project_health` — colored health badges per project,
     sorted worst-first.
   - An "Action inbox" section reading `v_action_inbox` — the unified ranked list.
   - A "Goals" panel reading `goals` + a small form to insert a goal (objective/metric/target).
   - Run `npm run build` and fix any SSR issues.

3. SCHEDULE everything (launchd agents on this Mac; reuse scripts/setup-scheduler.sh style):
   runner.py (KeepAlive); goals.py (every 30m); watchdog.py (every 5m); anomaly.py (hourly);
   digest.py (07:00); self_review.py (nightly); opportunity_scout.py (weekly);
   fix_propagation.py presets (weekly); research window (02:00); deploy window (03:00).
   Add WATCH_HEALTH_<PROJECT> env vars for each project's health URL so watchdog works.

4. EMBEDDINGS upgrade (semantic, not keyword):
   - Set EMBED_PROVIDER + key; backfill `knowledge.embedding` for existing rows.
   - Improve context_retrieval.py ranking with embeddings over a file/symbol index
     (build the index once per repo, cache it), keeping the rg fallback.

5. BATCH API for off-peak passes (≈50% cheaper): route opportunity_scout, optimizer, and
   research tasks through Anthropic's Batch API instead of interactive `claude -p`. Add a
   `batch_submit.py` that builds the batch, polls, and writes results back to outcomes.

6. DIGITAL-TWIN testing (near-zero-risk autonomous deploys): for risky tasks, create a
   Supabase BRANCH (supabase branching) + a Vercel PREVIEW deploy, run migrations/tests
   there, and only promote to prod (overnight window) if green. Wire into pr_integrate.py.

7. WATCHDOG depth: replace the health-URL-only check with real signals — Supabase logs
   (get_logs), Vercel deploy/health status, and (optional) Sentry — so it auto-remediates
   real errors, not just downtime.

8. Seed: add a `budgets` row + 1-2 `goals` for each real project you register in `projects`.

FINISH: checklist of what's wired, the live dashboard URL showing health/inbox/goals, the
installed schedules, and any decisions you need from me.
```
