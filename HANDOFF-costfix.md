# Handoff — CRITICAL: make Claude spend visible (so budgets/kill-switch actually work)

> Root cause of the ~$400 overspend: the runner calls `claude -p --output-format text`,
> which carries NO token/cost data, so cost_ledger records $0, and budget.py / usage_meter /
> the kill-on-cap logic are BLIND — they never trip. Fix: capture real cost from Claude Code's
> JSON output and route EVERY `claude -p` call through one metered helper. Do this before
> re-enabling the runner (it's currently paused via the global kill switch).

```
Fix Claude cost capture across the runner. Steps:

1. runner/claude_cli.py is ALREADY BUILT (Cowork) and tested. It exposes:
       run(prompt, model, cwd=None, env=None, project=None, max_turns=60, permission="acceptEdits", timeout=None)
       -> {"text","cost_usd","input_tokens","output_tokens","returncode","raw"}
   It already: honors the kill switch (returns returncode 75 + skipped='kill_switch' when paused),
   enforces hourly call/$ + daily $ circuit breakers (CLAUDE_MAX_CALLS_PER_HOUR / _USD_PER_HOUR /
   _USD_PER_DAY), uses `--output-format json` to capture total_cost_usd + usage, and records spend
   to provider_usage. VERIFY the JSON field names against the installed CLI
   (`claude -p "hi" --output-format json | jq`) and adjust the parse in claude_cli.run if needed.
   YOUR JOB is just to route every model call through it (steps 2-3).

2. runner.py: replace the inline `subprocess.run([CLAUDE_BIN,'-p',prompt,...,'--output-format','text'])`
   with claude_cli.run(...). Use the returned `text` everywhere the code currently scans `out`
   (RATE/EXHAUST detection, feedback.extract_and_store, verify, log_tail). In record(), set
   outcomes.usd = cost_usd and input/output_tokens from the helper — NOT the regex token parse.

3. Route the OTHER model-callers through claude_cli.run too, so ALL spend is metered:
   session_watcher._decide, opportunity_scout, capability_radar, distill, self_review,
   feedback_review, anomaly(if any), confidence, verify, auto_experiment, goals, ask, spec.
   Each should add its cost to provider_usage (provider='anthropic', project=<proj>) or outcomes
   so usage_meter sees the true total.

4. Make budgets enforce: after capture works, budget.allow() + usage_meter.over_budget() will
   see real $ and the runner's kill_switch + budget checks will actually pause at the cap.
   Set a sane default (e.g. budgets row per project; a global daily ceiling).

5. Add a test: assert claude_cli.run returns cost_usd > 0 for a real call, and that a task
   writes nonzero outcomes.usd. Without this, the guardrails are decorative.

6. ALSO confirm the session_watcher fix is active (skips '-wt'/unregistered transcripts, caps
   8/scan, files NO per-session approval) — that loop made ~64k Sonnet calls (~$400). It's the
   thing that must never recur.

7. SCHEDULER MUST HONOR THE KILL SWITCH (closes the residual-spend gap): in runner.py
   `_scheduler_tick`, before firing jobs, check kill_switch.is_paused() — when paused, skip ALL
   model-spending jobs (session_watcher, scout, radar, self_review, anomaly, spec, demand_mining,
   meta_loop, feedback_review, txn, batch, deploy); only allow resource_governor.py to run (it
   spends nothing and keeps the Mac safe). This makes the global pause a true full stop.

8. COSTLESS-FIRST POSTURE (owner's directive: spend only on clear ROI or a real emergency):
   - Trim runner.py `_SCHEDULE` so by DEFAULT only ZERO/near-zero-cost jobs run automatically:
     resource_governor (free) and watchdog (free unless it must remediate a real outage).
     Move the model-spending scouts (opportunity_scout/scout, capability_radar/radar,
     self_review, spec, demand_mining, meta_loop, anomaly's model call, batch) to OFF-by-default,
     gated behind an env flag (e.g. ENABLE_PROACTIVE_LOOPS=false). They run only when explicitly
     enabled or invoked on a task with expected ROI.
   - The runner should spend ONLY when there is a QUEUED task (a deliberate, ROI-justified unit
     of work) — never on speculative background scanning unless the owner turns it on.
   - claude_cli caps stay as the hard backstop: CLAUDE_MAX_USD_PER_DAY=30 (owner's max), and
     prefer cache/result-reuse/cheapest-model before ANY call.

When done: tell me, and I'll lift the global kill switch (controls.paused=false), restart, and
we scale to all projects with working budgets.
```
