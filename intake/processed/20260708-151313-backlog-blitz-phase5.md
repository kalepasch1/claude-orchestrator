PROJECT: beethoven

- id: backlog-blitz-watchdog-slo-verify
  title: Verify queued>0/running==0-for-15min watchdog auto-diagnoses and files one loud notification
  material: no
  model: sonnet
  depends: []
  proof: a synthetic queued>0/running==0 condition held for 15+ minutes produces exactly one notification with a diagnosis (billing/limits/locks/governor) attached, not silence and not spam
  prompt: |
    fleet_stuck_alarm.py already exists as of 2026-07-08, built by a concurrent fleet agent
    during this same session — check its current state before rebuilding. This is the exact gap
    that let the 2026-07-08 outage sit undetected until ~01:30: nobody was told queued was
    stacking up with zero running for hours. Confirm the module: (1) is wired into the periodic
    scheduler (grep runner.py's schedule table), (2) actually distinguishes root causes (billing
    pause vs rate limit vs stale lock vs governor clamp — not just "something's wrong"), (3)
    attempts a safe remediation appropriate to the cause before just alerting (e.g. if it's a
    stale lock, clear it; if it's a pause_arbiter-tracked cause, call recheck()), (4) files
    exactly ONE notification per incident, not one per periodic tick while the condition
    persists. If any piece is missing, add it. 20+ tests: each root-cause branch, the
    one-notification-per-incident dedup logic specifically (this is the easiest thing to get
    wrong — a naive implementation spams), and the "watchdog itself is silent when things are
    healthy" case.

- id: backlog-blitz-interlock-tests-expand
  title: Expand interlock test coverage to 20+ cases across db-env, kill_switch, and billing_guard
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m unittest runner.tests.test_db_env_interlock runner.tests.test_kill_switch runner.tests.test_billing_guard -v 2>&1 | grep -c "^test_"` reports >= 20
  prompt: |
    As of 2026-07-08 these three test files exist and pass but total well under 20 cases:
    test_db_env_interlock.py (3 cases: default-subscription-mode never loads key, deliberate
    fallback honored, no-key-stays-absent), test_kill_switch.py (2 cases: project pause scoping,
    resume-updates-existing-row), test_billing_guard.py (3 cases: key-presence warn-and-resume,
    real-spend pause-no-ttl, strict-key-presence pause-with-ttl). Extend each to genuinely new
    edge cases rather than padding — e.g. db-env: key present alongside ORCH_ALLOW_API_BILLING
    explicitly false vs unset vs "0"/"no" spellings, malformed .env lines, .env missing entirely,
    FDA-restricted read failure (OSError) fail-soft path; kill_switch: pause-then-resume
    round-trip where a newer row must win over a stale older row race, project-scope vs
    global-scope interaction, resume() called when nothing is paused; billing_guard: trip then
    auto-resume specifically when pause_arbiter's registered cause clears (already covered
    indirectly by test_pause_arbiter.py — cross-reference, don't duplicate, do add a
    billing_guard-specific integration case that exercises the real call chain end to end).
    Do not pad with trivial reflection tests just to hit the number — every case should catch a
    real regression.

- id: backlog-blitz-structured-logging
  title: Add ISO timestamp + job name to every runner/periodic log line (JSONL where cheap)
  material: no
  model: sonnet
  depends: []
  proof: after this change, `.runtime/logs/runner.log` lines each carry a parseable ISO8601 timestamp and job name, verified by a test that runs a periodic job and asserts the emitted line matches the expected format
  prompt: |
    Current runner.log lines look like `[sched] batch_fusion.py` and `[keepalive] starting
    runner at Wed Jul  8 10:49:27 EDT 2026` with no consistent machine-parseable timestamp
    format — this makes it hard to answer "how old is this log line" (I hit exactly this problem
    while investigating whether the artifacts-404 bug was still live or historical during this
    session — the log has no way to tell without walking line-by-line through a 13MB+ file).

    Do NOT introduce a new logging framework (repo convention: extend existing print paths).
    Add a small shared helper (e.g. in a `logutil.py` or wherever the existing print-based
    logging is centralized) that prefixes every runner/periodic print with an ISO8601 UTC
    timestamp and the emitting job/module name, and use it at every existing `print(...)` call
    site in runner/*.py periodic jobs — this is a mechanical, wide-reaching change, good
    candidate for batch_fusion once written. Where a line is already effectively structured
    (e.g. a dict being printed), emit JSONL instead of prefixing text. Keep the existing
    human-readable text content — only add the timestamp/job-name envelope, don't rewrite
    message wording repo-wide (that would touch far too many call sites' meaning and risk typos
    in log-grep patterns other modules rely on, like the "[sched]"/"[artifacts]"/"[integrate]"
    prefixes this exact session depended on to investigate).

- id: backlog-blitz-eval-gated-self-improvement
  title: Verify eval_harness.py does real before/after KPI comparison and auto-reverts no-movement changes
  material: no
  model: opus
  depends: [backlog-blitz-deploy-kpi-row]
  proof: a synthetic improve-lane change with a declared target KPI that doesn't move within a 24h simulated window produces an auto-filed revert proposal, referencing the KPI delta as evidence
  prompt: |
    eval_harness.py already exists as of 2026-07-08 — read it fully before assuming this is
    greenfield. Confirm each merged `improve`-lane change: (1) declares a target KPI at merge
    time (merged/day, first-pass rate, paused-minutes, $/task — reuse whatever KPI schema Part D
    of the meta-optimizer mission's scoreboard settled on if that's landed by the time you pick
    this up, don't invent a second one), (2) eval_harness.py actually compares the declared KPI
    24h before vs after the merge (not just logs the intent), (3) if the KPI didn't move (define
    "didn't move" precisely — e.g. within noise band vs a real regression threshold), it
    auto-files a revert proposal as an approval card, not a silent no-op. If eval_harness.py
    already does all three, this is a verification close with one real example attached showing
    a KPI delta from a merge this week. If any piece is a stub/TODO, implement it.
