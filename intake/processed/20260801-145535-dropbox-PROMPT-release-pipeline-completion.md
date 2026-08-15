# Release Pipeline Completion — windows, half-life, carding, fingerprint, SLOs (operator, 2026-07-31, CRITICAL)

project: beethoven

Already SHIPPED this session (verify + build on, do not redo): merge_train NameError/corruption
fixes + static_sanity gate; release-currency sentinel; catchup_drive; per-repo vercel.json
ignoreCommand (build only prod branch); release windows in release_train (_release_window_open).

BUILD (ordered; each independently mergeable):
1. BRANCH HALF-LIFE + AUTO-SUPERSEDE (do FIRST — it right-sizes everything after):
   For all ~2,800 origin agent/* branches across the 14 projects: classify each as
   (a) content already in base (merge-base ancestor OR content-equivalent patch) -> close branch,
   record disposition; (b) superseded by a newer branch touching the same files (newest-optimal
   wins) -> close + record supersede edge; (c) stale-but-unique (> N days, default 14) ->
   auto-rebase onto staging; if rebase fails, queue ONE consolidated rebuild task per initiative
   (not per branch); (d) live + unique -> keep. Persist a disposition ledger (coordination_tasks
   task_type=branch_disposition). Target: branch inventory < 25/project.
2. ORPHAN-BRANCH CARDING: for survivors of (1) with no approval card, use auto_queue_branches
   helpers to create cards (dedup by normalized slug) so the merge train can judge them. Never
   card a branch classified (a)/(b).
3. SKIP-REASON VISIBILITY: merge_train summary gains per-reason skip breakdown (no_card /
   verify_pending / waiting_window / stale / lock-busy) in the log line + JSON. A skip without a
   reason is the silent-failure class.
4. SPECULATIVE INTEGRATION TESTING (Mac-local, zero Vercel): maintain a shadow next-staging =
   staging + all green branches per project; run the project test suite on it each cycle;
   cross-branch breakage files repair tasks the hour it appears, not at merge time.
5. SESSION-CONTINUITY (app-side, one shard per Nuxt app): version-aware soft update — client
   polls a build-id endpoint; on change show a non-blocking "New version available — refresh when
   ready" toast; NEVER force-reload. Also enable Vercel Skew Protection per project (note: if the
   dashboard toggle is required, emit an operator card listing exact clicks).
6. DEPLOY-FINGERPRINT VERIFICATION (per release window): after a window's build goes Ready,
   verify the LIVE site: route manifest sample, key feature markers (per app: gradient card,
   token billing UI, standing-IOI panel...), build-id vs promoted SHA. Mismatch -> CRITICAL
   coordination alert deploy_fingerprint_alert. "Ready" must mean "improvements on screen".
7. OUTCOME SLOs: extend release_currency_check with per-project SLOs — merge-latency p50 < 1h
   (green->staging), prod-lag <= 1 release window, branch inventory < 25, Vercel prod builds/day
   <= windows+P0 count (cost SLO). Publish a scorecard to the progress console; breaches alert.
Tests for every piece (the supersede classifier especially: ancestor, content-equivalent,
superseded, unique cases). All commits kalepasch1 <kalepasch@gmail.com>. Never force-push.
