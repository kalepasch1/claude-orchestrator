PROJECT: beethoven

- id: backlog-blitz-vercel-deploy-wiring
  title: Wire merge-train success on web/ to Vercel deploy hook, smoke test, promote-or-rollback
  material: yes
  model: opus
  depends: [backlog-blitz-verify-artifacts-404-merge-train-500]
  proof: a real merge to web/ triggers a recorded Vercel deployment with a green smoke-test row in the outcomes/deploy log, or (if blocked on missing secrets) an operator approval card is filed naming exactly which env var is missing
  prompt: |
    deploy_verify.py already reads VERCEL_TOKEN / VERCEL_TEAM_ID from env and guards to
    status-from-git-only when absent — check runner/.env and fleet secrets for whether a real
    Vercel token + deploy hook URL are already configured before assuming this needs new
    plumbing. This whole task is MATERIAL (deploy wiring, per repo guardrails) — file ONE
    approval card up front covering: what triggers a prod promotion, what the smoke test checks,
    and the rollback path, before wiring it live.

    1. Re-enable `releasetrain` and `deployverify` periodic jobs if currently paused/skipped —
       check current pause state via pause_arbiter / kill_switch scoped to these jobs first.
    2. On merge-train success for a task targeting `web/`, trigger the Vercel deploy hook (the
       hook URL must be an env var — VERCEL_DEPLOY_HOOK_URL or similar — never hardcoded, never
       committed to git even in an example value).
    3. Poll for the resulting preview URL (deploy_verify.py already has Vercel API polling
       logic — extend, don't fork).
    4. Run a smoke test against the preview URL: page loads (200 + non-empty body), auth
       redirect works (hit a protected route, expect a redirect not a 500), tasks board renders
       (look for a known DOM marker or API response shape).
    5. On green smoke test, promote preview to production via the Vercel API. On smoke failure,
       do NOT promote — log the failure with the specific check that failed, leave production on
       the last-known-good deployment.
    6. If VERCEL_TOKEN / deploy hook URL genuinely aren't configured anywhere reachable by the
       runner, don't fake success — file an operator approval card naming exactly which secret
       is missing and where to add it (runner/.env, never committed), and stop there.

    20+ tests: smoke test failure blocks promotion, missing token degrades to status-only (no
    crash), hook URL never appears in logs/commits, retry/backoff on Vercel API rate limits,
    concurrent deploy attempts don't race.

- id: backlog-blitz-deploy-kpi-row
  title: Record a deploy KPI row after every deploy attempt, surface on dashboard
  material: no
  model: sonnet
  depends: [backlog-blitz-vercel-deploy-wiring]
  proof: after a deploy attempt (success or failure), a new row exists with merged-count-today, first-pass-rate, deploy-status, paused-minutes-today, and the web dashboard renders it
  prompt: |
    Check whether scoreboard.py (seen in-flight from a concurrent agent as of 2026-07-08, may
    also be feeding the separate meta-optimizer mission's Part D1 KPI scoreboard — check its
    docstring/columns before assuming this is unbuilt) already covers this. If it does, extend
    it with the deploy-specific fields listed above rather than building a second KPI table. If
    it's product-scoreboard-only and doesn't cover deploy attempts, add a `deploy_kpi` row
    written after every deploy attempt (success or failure) with: merged count today, first-pass
    rate, deploy status, paused-minutes today. Surface it on the existing dashboard (web/pages) —
    reuse existing card/table components, don't invent a new dashboard section pattern.
