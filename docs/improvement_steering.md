# Improvement Steering & Non-Interrupting Background Optimization

_Internal engineering documentation. Grounded in the actual mechanisms in `runner/`, not
aspirational. Every claim below cites the file/function that implements it._

## The core property being documented

Two things are true at the same time in this fleet, and the mechanisms below are what make
both true simultaneously:

1. **The system improves itself continuously** — new capabilities, routing decisions, context
   trims, and queue-quality fixes are discovered and published by background jobs.
2. **In-flight and new coding work is never blocked, paused, or restarted to pick those
   improvements up.** A task claimed one second before an improvement lands, and a task
   claimed one second after, both run correctly — the second one just runs slightly better.

This second property is the "embedded coding optimize capabilities" differentiator: improving
the fleet is not a deploy event.

## How improvements are steered

**1. Proactive discovery loops (gated, cost-bounded, background-only).**
`runner.py`'s `_PROACTIVE` set (`self_review.py`, `maturity.py`, `demand_mining.py`,
`capability_radar.py`, `meta_loop.py`, `feedback_review.py`, `experiment_portfolio.py`, plus a
few shorthand jobs) runs only when `ENABLE_PROACTIVE_LOOPS=true` (`_proactive_on()`), and their
spend is deliberately *not* routed through the same `claude_cli` path counted against the
day's model-spend cap — they are accounted for separately so exploratory self-improvement work
can never crowd out the primary task queue's budget. These are periodic dispatches
(`_PERIODIC`/`_fire_periodic`), not inline steps inside `run_task()` — a slow or stuck
discovery job cannot block a task from being claimed or merged.

**2. Measurement closes the loop.** `scoreboard.py` (merge rate, first-pass rate,
paused-minutes, queue mix — every 10 min), `cost_intelligence.py` (usd/merge, indirect-reuse
value, competitor cost comparison — daily), and `improvement_roadmap.py` (staged, disclosed-
assumption projection of how far current levers could close the cost gap — daily) are the
feedback instruments: every proposed improvement is judged against the same ratios it's meant
to move, not against a self-reported "it should help" claim.

**3. Publishing an improvement is a database write, not a deploy.** A capability
(`capabilities` / `capability_instances` tables), a compiled intent (`intent_compiler.py`), or
a zero-token replay proof (`cade_tournaments.zero_token_patch`) becomes available to every
runner the moment the row commits — every runner reads these tables fresh per task via
`db.select()`, there is no in-process cache of "the current capability set" that a running
process would need to be restarted to refresh. This is the specific mechanism that makes
improvement propagation non-interrupting: **the thing that changes is data the next task reads,
not code the current process is running.**

**4. Config changes are the same story.** Per `CLAUDE.md`'s fleet-wide-config convention,
tunable behavior changes go through the central `fleet_config` table via `fleet_control.py`'s
in-process gateway, applied to all machines without SSH or a restart step — the same
propagation model as capabilities, for the same reason.

## How in-flight work stays uninterrupted while this happens

**1. Task claiming is atomic and optimistic, not locked.** `db.claim_task()` does a
conditional `QUEUED -> RUNNING` PATCH; multiple runners (and, per the containerization
scaffolding in `deploy/`, multiple machines) can poll the same queue simultaneously with no
central scheduler to fall over or need to pause during a change.

**2. Every task gets an isolated git worktree** (`setup-worktrees.sh`, `git worktree add -f`
in `run_task()`), not a shared checkout. A concurrent code-quality or toolchain improvement
landing in `main` does not touch a task's in-progress worktree; the task's base ref is resolved
once at claim time (`_resolve_task_base`) and the diff is built and verified against that
isolated copy.

**3. Pausing is scoped, typed, and self-expiring — not a global freeze.**
`pause_arbiter.py` pauses by *reason code* with an optional TTL, not as an undifferentiated
kill switch: a billing-guard trip, a toolchain failure, and an operator-requested pause are
independently tracked and independently lifted (`recheck()`), and three consecutive
identical-reason trips escalate to a filed approval rather than looping forever. Critically,
`runner.py`'s `_SAFE_WHEN_PAUSED` set (which now includes `pause_arbiter.py`,
`fleet_stuck_alarm.py`, `queue_bankruptcy.py`, `scoreboard.py`, `toolchain_gate.py`,
`context_cache_distill.py`, `cost_intelligence.py`, and `improvement_roadmap.py`) keeps
telemetry, self-healing, and the pause-lifting logic itself running *even while the fleet is
paused* — a pause never blinds the system to the condition that would let it safely resume.

**4. Improvement work that touches the runner's own hot path is opt-in and reversible, not a
silent swap.** `ORCH_LEAN_MODE` (`_LEAN_MODE_ON()`) is explicitly scoped to periodic-only
bookkeeping for the heaviest self-play subsystems (`_LEAN_MODE_SKIP`); the runner.py comment at
the gate is explicit that this must be A/B'd against `scoreboard.py`'s real merge-rate and
usd/merge numbers before being left on, and it never touches the inline model-routing or
zero-token-replay logic a task's correctness depends on mid-run.

**5. Toolchain and dependency changes are pre-flighted, not discovered mid-task.**
`toolchain_gate.is_ready_cached(project_id)` is checked in `run_task()` before work starts; a
project with a known-broken toolchain has its task returned to `QUEUED` with a note rather than
failing partway through a run, and repair happens as a separate, non-blocking periodic job.

## What this adds up to

An improvement — a new reusable capability, a cheaper model route, a smaller context window, a
queue-quality fix — is discovered by a background, cost-bounded, independently-scheduled job;
measured against the same efficiency ratios every other change is measured against; and
published as a database row that the *next* task claim reads fresh. No runner restarts, no
queue drains, no global pause, and no in-flight task is ever required to make an improvement
live. The only thing "in the background" means here is "not on the critical path of a task
that's already running" — it does not mean "invisible" or "unmeasured."
