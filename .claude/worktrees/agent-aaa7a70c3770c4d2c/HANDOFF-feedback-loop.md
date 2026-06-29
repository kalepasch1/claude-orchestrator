# Handoff — agent→orchestrator feedback loop (finish)

> Cowork built the core and applied live schema 0006 (`orchestrator_feedback`). Built +
> WIRED: feedback.py (agents emit a <orchestrator_feedback> block; runner auto-harvests it;
> CLI for interactive sessions) and feedback_review.py (clusters new feedback by category →
> orchestrator self-improvement proposals, preference-gated, marks 'triaged'). The task
> prompt now tells every agent how to report friction. Finish these:

```
1. SCHEDULE feedback_review.py daily (launchd), alongside self_review.py — telemetry-driven
   + experience-driven self-improvement together.

2. AUTO-EXPERIMENT wiring (the 10x): when a feedback cluster suggests a concrete knob change
   (e.g. context 'CONTEXT_MAX_FILES too low', model 'route refactors to Sonnet'), turn it into
   an A/B run via eval_harness.py BEFORE adopting — current vs proposed setting on held-out
   tasks — and only file the proposal as 'recommended: adopt' if the candidate wins. Close the
   loop so good feedback auto-validates.

3. PER-CATEGORY ROUTING: give each feedback category an owner that can act on an APPROVED
   proposal — context→context_retrieval (MAX_FILES), model→bandit priors, prompt→caching
   prefix/template, guardrail→guard rules, rate_limit→adaptive concurrency, strategy→planner.
   On approval, apply the change on a branch through CI (revertible).

4. DASHBOARD: a "Feedback" view (web/pages) — counts by category/severity, recent items, and
   status (new/triaged/applied). Add a one-click "interactive feedback" box that inserts a row
   (source='human'), so you can teach the orchestrator directly too.

5. INTERACTIVE INTAKE for VS Code sessions: add a tiny `/feedback` convention or a Claude Code
   slash command that shells `python3 runner/feedback.py --category .. --observation ..` so the
   interactive sessions (not just headless runs) feed the loop.

6. REPUTATION WEIGHTING: weight feedback by the outcome of the task it came from (feedback from
   tasks that later merged/passed is worth more than from failed ones); store the weight and use
   it in feedback_review clustering thresholds.

FINISH: checklist, feedback_review scheduled, dashboard Feedback view live, and confirm the
auto-experiment gate runs before any feedback-driven orchestrator change is adopted.
```
