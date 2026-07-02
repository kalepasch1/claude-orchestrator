# Handoff — route every app's AI/API calls through the shared triage/optimization service

> Cowork built the orchestrator-side service (`app_triage.py`), the perpetual review loop
> (`app_triage_review.py`), and the ledger tables (`app_operations`, `app_op_routes`). This handoff
> wires each product to USE it, so any AI/API work an app does is continuously optimized to the
> lowest cost / highest quality — reviewed by the same cross-model bots we use internally.

## What already exists (orchestrator side, live)
- `app_triage.route(app, operation, task_class)` → cheapest capable provider+model (honors any
  learned per-operation route in `app_op_routes`).
- `app_triage.run(app, operation, prompt, task_class)` → triage + execute (metered) + log to
  `app_operations`.
- `app_triage_review.run()` (scheduled every 30 min) → cheap cross-model review scores each op's
  cost/quality, then writes the cheapest route that holds quality to `app_op_routes` and files an
  approval when a cheaper-equal-quality switch is available.
- Supabase tables `app_operations` (ledger) and `app_op_routes` (recommendations) are migrated.

## Task for the swarm (per app)
```
For THIS app, make every AI/API call go through the shared triage service instead of a hardcoded
provider. Two supported integration modes — pick per app:

A) Python apps: `import app_triage` (or copy the thin client) and replace direct OpenAI/Anthropic/etc
   calls with:
       r = app_triage.run(APP_NAME, OPERATION_NAME, prompt, task_class=<mechanical|qa|review|rating|
                          plan|build|hard|security|legal>)
       text = r["text"]
   Keep the operation name STABLE (it's the optimization key).

B) JS/TS/Go/other apps: call a small `triage` Supabase Edge Function that wraps app_triage.route()/
   run() and returns {provider, model, text, cost_usd}. Build the edge function once
   (supabase/functions/triage) reading SUPABASE_SERVICE_KEY, then have the app POST
   {app, operation, task_class, prompt}. Cache the returned route locally per operation for a few
   minutes to avoid a hop on every call.

RULES:
- Classify each call site's task_class honestly (a summarize/extract = qa/rating; a code edit =
  build; a legal/financial judgement = legal/hard). The class sets the capability floor.
- NEVER send customer PII into the orchestrator. app_operations stores metadata (provider, model,
  cost, latency, op name) — NOT payloads. Grade quality on descriptors, not raw user data.
- This must never make an app more expensive: if no cheaper capable provider is configured, the app
  keeps its current provider (route() returns the policy default) and just logs for review.
- Add a per-operation kill switch: if triage is unavailable, fall back to the app's prior default so
  no user-facing call fails.

ACCEPTANCE: every external AI/API call in the app flows through triage; app_operations shows rows for
each operation; after a review cycle, app_op_routes has a recommended cheapest-good provider per
operation; a deliberately-expensive call gets an approval card proposing a cheaper route.
```

## Rollout order
Start with ONE app that makes obvious AI calls (best candidate: whichever app already calls an LLM in
a hot path). Prove `app_operations` fills and `app_op_routes` learns a cheaper route with held
quality. Then fan out to the rest — the swarm can do this itself as normal tasks once seeded.
```
