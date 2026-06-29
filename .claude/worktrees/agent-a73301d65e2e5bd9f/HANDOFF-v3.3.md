# Handoff prompt v3.3 — paste into Claude Code to finish the twelve

> I (Cowork) implemented the codeable parts of all twelve ideas as runner modules (they
> compile + import clean) and wired confidence-gating, blast-radius, and replay into
> `runner.py`. Live Supabase is migrated through 0004 (two-key columns on `approvals`,
> `runs` table). Your job: finish wiring, schedule, surface in the UI, and add the
> infra-heavy parts. Work in small verified steps; never commit secrets; report a checklist.

```
Continue the Claude Orchestrator. New modules already present in runner/ (import-clean):
confidence.py, blast_radius.py, preference.py, roi.py, ask.py, quality_gate.py, replay.py,
spec.py, chaos.py, canary.py, transaction.py. Live DB is at migration 0004. Finish the
twelve features below — each lists what EXISTS and what's LEFT for you.

1. SPEC-AS-SOURCE-OF-TRUTH — exists: spec.py (drift check + queue). Left: schedule it per
   repo (weekly); add a SPEC.md template; let `planner.py` generate code FROM SPEC.md.

2. CONFIDENCE-GATED AUTONOMY — exists + WIRED: confidence.gate() decides auto / review /
   two_key before integrate (runner.py). Left: expose CONFIDENCE_THRESHOLD per project;
   show the score on task cards in the dashboard.

3. BLAST-RADIUS ANALYSIS — exists + WIRED: blast_radius.note_for_task() injects dependents
   into the prompt; radius_after() for the actual diff. Left: feed radius_after() into the
   verify step so missing dependent-tests block the merge.

4. METRIC-GATED CANARY — exists: canary.evaluate() (error_rate/p95/conversion thresholds).
   Left: call it from the overnight deploy step (deploy-window) — promote on 'promote',
   auto-rollback on 'rollback'; set METRICS_URL + CANARY_* per project.

5. MUTATION + PROPERTY TESTING — exists: quality_gate.run(). Left: call it inside verify
   (after unit tests, before integrate); configure MUTATION_CMD/PROPERTY_CMD per repo;
   block merge if it fails.

6. PREFERENCE LEARNING (RLHF-lite) — exists: preference.score()/should_suppress() from your
   approve/deny history. Left: in opportunity_scout/optimizer, suppress or down-rank
   proposals below PREF_SUPPRESS_BELOW; show predicted-approval on cards.

7. CROSS-REPO REFACTOR TRANSACTIONS — exists: transaction.py (members/status/resolve via a
   'txn:<id>' note convention). Left: a scheduled coordinator that calls resolve() and, when
   ready, ff-merges ALL member branches (or aborts all); a `txns` table + UI to create one.

8. TWO-KEY APPROVALS — exists: confidence flags high-risk -> files approval with
   approvals_required=2; DB columns added (approvals_required, second_approver). Left:
   ENFORCE in the dashboard/edge: an approval with approvals_required=2 only flips to
   'approved' after TWO distinct authenticated users approve (record second_approver).

9. ROI SCORING — exists: roi.report() (cost-per-merge, pass-rate per project). Left: add a
   dashboard panel; feed ROI into scheduling so low-ROI projects get less concurrency.

10. DETERMINISTIC REPLAY — exists + WIRED: replay.capture() snapshots every run to `runs`;
    replay.replay(run_id, repo) re-runs it. Left: a dashboard "runs" view with a Replay
    button; bisect helper across runs.

11. NL ANALYTICS — exists: ask.py answers questions over live telemetry. Left: a dashboard
    search box that calls a small edge function wrapping ask.py (or run server-side).

12. CHAOS DRILLS — exists: chaos.py (stale-runner, fake-fail; gated by CHAOS_ENABLED). Left:
    schedule weekly in a STAGING context only; add an assertion step that verifies the
    self-heal/visibility actually happened and reports pass/fail.

ALSO (from the v3.2 handoff, still open): wire health/inbox/goals into the dashboard;
schedule all periodic jobs (launchd); embeddings upgrade for knowledge + context_retrieval;
Batch API for off-peak passes; Supabase-branch digital-twin + Vercel preview per PR.

FINISH: checklist of what's wired/scheduled, the live dashboard URL, env you need me to set,
and any decisions for me.
```
