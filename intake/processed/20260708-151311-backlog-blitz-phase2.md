PROJECT: beethoven

- id: backlog-blitz-verify-artifacts-404-merge-train-500
  title: Confirm artifacts-store 404 and canonical-merge-train 500 are actually fixed, not just refactored away
  material: no
  model: sonnet
  depends: []
  proof: run the live merge/integrate path against a real recovery-class task and grep runner.log for zero new "DB store failed" / "canonical train failed" lines in the last 500 log lines after the run
  prompt: |
    As of 2026-07-08 ~10:50 EDT, `runner.log` shows repeated recent lines:
      `[artifacts] DB store failed for <slug>: HTTP Error 404: Not Found`
      `[integrate] ZERO-TRUST WARNING: canonical train failed, using legacy path: HTTP Error 500: Internal Server Error`
    But grepping current runner/*.py source for these exact strings returns ZERO matches — the
    code that emitted them appears to have already been refactored/replaced by a concurrent
    fleet agent. This is ambiguous: either (a) it's genuinely fixed and the log lines are stale
    history from an earlier process generation, or (b) the log strings changed wording but the
    underlying 404/500 bug is still live under a new message.

    1. Find the current code path that stores task artifacts to Supabase and the current
       "canonical merge train" integration call (search for how `[integrate` / artifact-store
       log prefixes are emitted now — they may have moved files/renamed).
    2. Reproduce: trigger it against a real or synthetic recovery/release-fix task and watch for
       HTTP errors.
    3. If still broken: the artifacts store 404 likely means the Supabase table/endpoint the
       write targets doesn't exist — check migrations under supabase/migrations/ for a matching
       table; if missing, add a migration (material: this specific sub-step needs one approval
       card since it's schema). The merge-train 500 needs the actual failing endpoint/request
       identified (log the raw response body, not just the status code) and either fixed or the
       legacy-fallback log line upgraded to include the real underlying error so it's not a
       silent swallow.
    4. If already fixed: close this task with a note pointing to the commit/file that fixed it,
       and no further code change needed — do not invent a fix for a bug that's already gone.

- id: backlog-blitz-toolchain-preflight-verify
  title: Verify hermetic worktree toolchain preflight actually blocks claims on red projects
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m unittest runner.tests.test_toolchain_gate` exits 0 and a manual check shows a project with missing npm gets marked blocked, not claimed
  prompt: |
    toolchain_gate.py and runner/tests/test_toolchain_gate.py already exist and were being
    actively modified by a concurrent fleet agent as of 2026-07-08. Check current state first.

    Confirm it does all of: runs a per-project node/npm preflight once per day (not per-task),
    caches `npm ci` output in a shared per-project cache, makes that node_modules available to
    each new worktree (symlink or copy — copy is safer for isolation, symlink is cheaper; pick
    one and document why), and — critically — that a task CANNOT be claimed for a project whose
    preflight is currently red (verify this is actually wired into the claim path, not just
    computed and ignored). If the block-on-claim wiring is missing, add it. If everything already
    works, extend the test suite to 20+ cases covering: missing node entirely, missing npm,
    npm ci failure, stale cache expiry, concurrent preflight runs for the same project, and the
    claim-path block itself (a red project's tasks must not be pulled into a build).

- id: backlog-blitz-shelf-integration-audit
  title: Audit the automated agent/* branch bulk-integration sweep for stall/backlog
  material: no
  model: sonnet
  depends: []
  proof: `git for-each-ref --format='%(refname:short)' 'refs/heads/agent/*' | while read b; do git rev-list --count master.."$b"; done | awk '{s+=$1}END{print s}'` trends toward 0 over the following 24h (record before/after counts in the task outcome)
  prompt: |
    As of 2026-07-08 there are 178 agent/* branches, 68 of which are ahead of master with
    unmerged commits — this is real shelf inventory. runner.py already has an automated
    "integrate-existing" sweep (grep for `integrate-existing` in runner/runner.py) that merges
    branches whose agent run already committed work, without re-running the agent. It appears
    to be actively running (log lines like
    `[integrate-existing] qafix-tomorrow-...: branch ahead of main -> skip agent, integrate
    directly` are present in runner.log).

    Don't build a new integration mechanism — one already exists and is running. Instead:
    1. Measure the current backlog (68 branches ahead as of this writing) and confirm the sweep
       is actually processing it down over time, not just logging attempts that fail.
    2. If it IS working, this task is done — record the before/after count delta as proof.
    3. If it's stalled (branches ahead count isn't shrinking), diagnose why (conflict storms?
       ordering issue — the mission notes branches should be processed in rebase-stack order,
       related branches sequentially, to avoid conflict pileups) and fix the ordering/backoff
       logic in the existing sweep rather than writing a parallel new one.
