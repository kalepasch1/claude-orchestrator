PROJECT: galop

# Fourth batch — real ML intelligence, real-time, integrity, compliance,
# retention, reach, and operating the autonomous machine. Independent of the
# three prior galop intake files. Dependencies are WITHIN this file only;
# external prereqs noted in prose. Several tasks are large/high-risk — split into
# one-deliverable units and chained with `depends`. Model=opus on the risky ones.

- id: ml-feature-store
  title: Historical feature store for a real win-probability model
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND live SQL check on Supabase project qlzsnuspiypyejaqcdad shows a feature table/matview populated from resolved races with per-runner features + a finish_pos label, and that it is NOT exposed to anon/authenticated for live races
  prompt: |
    Build the dataset that a real model trains on. Add a migration that materializes, from
    RESOLVED races only, a per-runner feature row (odds/implied prob, draw, field size,
    race_type, going/class if present, market move from open->now, plus the current
    heuristic sub-signals) with the finish_pos-derived label (won 1st: bool). Keep it
    service-role/definer only — it carries labels, so it must never be readable for live
    races (mirror the finish_pos lockdown). Add a refresh path (cron RPC or job). Apply to
    qlzsnuspiypyejaqcdad. Acceptance: the feature table populates from history, has a clean
    label column, and is not anon/authenticated-readable.

- id: ml-train-backtest
  title: Train + backtest a win-probability model beating the heuristic
  material: yes
  model: opus
  depends: [ml-feature-store]
  proof: a training script under racefeed/ml/ runs and writes a backtest report showing out-of-sample log-loss AND calibration better than the current rf_runner_intel heuristic baseline on a held-out season
  prompt: |
    Replace cosmetic "intelligence" with a real edge. Add an offline training pipeline
    (racefeed/ml/, Python or JS) that reads the ml-feature-store export, trains a
    gradient-boosted win-probability model, and BACKTESTS it out-of-sample (hold out the
    most recent season) reporting log-loss, AUC, and a calibration curve vs the current
    heuristic baseline. Emit a versioned model artifact + a metrics report committed under
    racefeed/ml/reports/. Do NOT wire it into serving yet (that is ml-serve-aiscore).
    Acceptance: the script runs deterministically, the report exists, and the model beats
    the heuristic baseline on out-of-sample log-loss + calibration.

- id: ml-serve-aiscore
  title: Serve the trained model behind ai_score (with heuristic fallback)
  material: yes
  model: opus
  depends: [ml-train-backtest]
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND live SQL check on qlzsnuspiypyejaqcdad shows rf_runner_intel win_prob is model-backed for covered races, winner-free, shape-identical, and falls back to the heuristic when the model is unavailable
  prompt: |
    Wire the trained model into the live product. Serve predictions via a precomputed
    per-runner table (written by a job) or an edge function, and update rf_runner_intel to
    use the model's win_prob when available, falling back to the existing heuristic
    otherwise — keeping the output shape IDENTICAL and strictly winner-free (no finish_pos
    at serve). Apply to qlzsnuspiypyejaqcdad. Acceptance: intel returns model-backed
    probabilities for covered races, identical shape, clean fallback, no result leak.

- id: intelligence-api
  title: Galop Intelligence — public/licensed win-probability signal API
  material: yes
  model: sonnet
  depends: [ml-serve-aiscore]
  proof: a live check shows a rate-limited, key-authenticated, winner-free endpoint returns per-race win-probability signals (no finish_pos/winner)
  prompt: |
    Turn the model into a product + data flywheel. Add a rate-limited, API-key-authed edge
    function (racefeed/supabase/functions/) exposing per-race win-probability + edge
    signals for upcoming/live races — strictly winner-free. Include usage metering. Deploy
    to qlzsnuspiypyejaqcdad. Acceptance: endpoint requires a key, is rate-limited, returns
    signals with no result leak, and logs usage.

- id: realtime-sockets
  title: Supabase Realtime for live pools, odds drift, and co-watch picks
  material: yes
  model: opus
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes AND live check shows realtime publication is enabled only on winner-free tables/columns and a client hook receives updates
  prompt: |
    Replace polling with push. Enable Supabase Realtime on the winner-free pool/odds
    surfaces (e.g. race_pools/peer_pools sizes, indicative odds) and add
    hooks/useRealtimeRace.ts that subscribes to a race's live pool/odds and (if present)
    friends' picks, updating the card in place. CRITICAL: never add races.winner or
    race_runners.finish_pos to any realtime publication. Apply publication config to
    qlzsnuspiypyejaqcdad. Acceptance: a pool/odds change pushes to a subscribed client;
    the publication excludes all result columns; tsc + tests pass.

- id: integrity-anti-abuse
  title: Collusion + bonus-abuse detection for pools, referrals, and guest coins
  material: yes
  model: opus
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `node --test lib/integrity.test.ts` passes AND live SQL check on qlzsnuspiypyejaqcdad shows an abuse_flags table + a service-role detection RPC/job
  prompt: |
    Protect the economy before it scales. Add a detection layer: pure scoring in
    lib/integrity.ts (+ lib/integrity.test.ts) for signals like shared device/IP,
    coordinated peer-pool entries, referral rings, and abnormal win/withdraw-of-coins
    velocity; plus a service-role RPC/job that writes to an abuse_flags table for review
    and can soft-limit flagged accounts. Apply schema to qlzsnuspiypyejaqcdad. No
    auto-punishment beyond soft limits (human review for bans). Acceptance: scoring has
    unit tests; flags persist; detection is service-role only.

- id: responsible-gaming-suite
  title: Deposit/session/loss limits, self-exclusion, cool-off, age/region gate
  material: yes
  model: opus
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes AND live SQL check on qlzsnuspiypyejaqcdad shows a bet exceeding a set limit (or during self-exclusion/cool-off) is rejected by the submit RPCs
  prompt: |
    Make responsible gaming a first-class system (and a distribution unlock). Add
    rg_limits(user_id, daily_stake_cap, session_minutes, loss_cap, self_excluded_until,
    cool_off_until, age_verified, region) + enforcement inside ALL bet submit RPCs
    (rf_submit_win/exotic/group/acca/pool) that rejects a bet violating a limit,
    self-exclusion, or cool-off, and a client settings surface to set them. Add an
    age/region gate at onboarding. Apply to qlzsnuspiypyejaqcdad. Acceptance: a bet over a
    configured cap or during self-exclusion is server-rejected; limits are user-settable;
    RG counters already in the app feed into session limits.

- id: churn-winback
  title: Churn scoring + automated win-back lifecycle
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND live check shows a service-role job computes a per-user churn score and enqueues a gated win-back action for at-risk users (respecting notification prefs)
  prompt: |
    Build the retention engine. Add a service-role job/RPC that scores churn risk from
    recency/frequency/streak-break/balance signals and, for at-risk users, enqueues the
    best win-back (a free bet, a friend's hot slip, a clan nudge) via the existing push/
    notification infra — respecting prefs + quiet hours + RG self-exclusion. Persist the
    action + outcome for measurement. Apply any schema to qlzsnuspiypyejaqcdad. Acceptance:
    an at-risk synthetic user is scored and gets exactly one gated win-back; opted-out /
    self-excluded users get none.

- id: handicapping-academy
  title: Learn-to-bet academy (interactive lessons + coin rewards)
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes AND live SQL check on qlzsnuspiypyejaqcdad shows rf_claim_lesson grants a one-time reward per lesson (no double-claim)
  prompt: |
    Reduce early churn + feed the skill ladder. Add short interactive lessons (reading the
    AI score, dutching, each-way value, bankroll) as a new surface, with a one-time coin
    reward per completed lesson via rf_claim_lesson(p_lesson_id) (authenticated, idempotent
    per user+lesson). Apply schema to qlzsnuspiypyejaqcdad. Surface an "Academy" entry from
    the Rewards HUD / profile and an occasional feed chapter. Acceptance: completing a
    lesson grants its reward exactly once; content renders; no double-claim.

- id: tentpole-event-mode
  title: Live tentpole event mode (Derby/Ascot day) with countdown + sprint board
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes AND live SQL check on qlzsnuspiypyejaqcdad shows an events config table drives a featured event window
  prompt: |
    Manufacture DAU spikes. Add a config-driven live event (events table: id, name,
    starts_at, ends_at, featured_race_ids, boosts) that, during its window, surfaces a
    countdown + special event UI in the feed, a dedicated event leaderboard sprint, and
    optional reward boosts. Apply schema to qlzsnuspiypyejaqcdad. Acceptance: a configured
    event window drives the countdown + event board; outside the window the feed is normal.

- id: android-web-parity
  title: Android + responsive web parity (TAM expansion)
  material: no
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npx expo export --platform web` succeeds AND `npx expo export --platform android` succeeds
  prompt: |
    Expand the addressable market on mostly-existing code. Audit the feed + betting + HUD
    surfaces for Android + react-native-web parity: fix platform-conditional code, video
    autoplay/muting on web, gesture + safe-area differences, and layout on wide/web
    viewports; ensure the web build is shareable/linkable (deep links resolve). Do not
    regress iOS. Acceptance: web + android exports succeed; the feed, bet slip, parlay,
    and HUD render and function on both; iOS unaffected.

- id: observability-slas
  title: Settlement-SLA, feed-health, and economy-drift dashboards + alerts
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND live check on qlzsnuspiypyejaqcdad shows monitoring queries/functions for resolution latency, stuck bets, feed staleness, and coins-in-vs-out, with a gated alert path
  prompt: |
    Give the autonomous machine a safety net. Add monitoring: settlement latency + stuck
    open bets (bets long past a resolved race), feed staleness (no fresh races), payout
    anomalies, and economy drift (coins wagered vs won vs granted). Expose as service-role
    queries/edge functions + a gated alert (Slack/webhook or push to an ops channel). Apply
    any schema to qlzsnuspiypyejaqcdad. Acceptance: each check returns real numbers; a
    synthetic stuck bet / stale feed triggers exactly one alert; alert path is not
    anon-callable.

- id: experimentation-platform
  title: A/B platform — holdouts, CUPED, guardrail metrics, auto-rollback
  material: yes
  model: opus
  depends: [observability-slas]
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `node --test lib/experiments.test.ts` passes AND a sample experiment shows assignment + a guardrail check + a rollback hook
  prompt: |
    Turn "10-200X" into a measured loop. Add an experiment framework: deterministic
    server-side assignment (stable bucketing), holdout support, CUPED variance reduction on
    a key metric, guardrail metrics (RG limits, economy drift, crash rate) that auto-flag,
    and a rollback hook that disables a variant when a guardrail regresses. Pure stats in
    lib/experiments.ts (+ lib/experiments.test.ts); wire flag reads into the bet-slip +
    feed surfaces. Apply any config schema to qlzsnuspiypyejaqcdad. Acceptance: assignment
    is deterministic + tested; CUPED reduces variance on a sample; a tripped guardrail
    flips the variant off.

- id: creator-duets
  title: Creator reactions/duets over race clips into the feed (UGC)
  material: yes
  model: opus
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND live check on qlzsnuspiypyejaqcdad shows a user_clips table + storage bucket with RLS (author-write, public-read only after moderation flag) and a feed read path for approved clips
  prompt: |
    Make the format itself viral. Let users record a short reaction over a race clip or a
    slip and post it into the feed. Add a Supabase Storage bucket + user_clips table
    (author, race_id, media_path, caption, moderation_status) with RLS (author writes;
    public reads only moderation_status='approved'), a capture/upload path (expo camera +
    upload), and a feed renderer that interleaves approved clips. Gate publishing behind a
    moderation step (status defaults to 'pending'). Apply schema to qlzsnuspiypyejaqcdad.
    Acceptance: a user can record+upload; clips are private until approved; approved clips
    render in the feed; RLS enforced.

OPERATOR:
  - ml-train-backtest needs a training environment (Python/GPU or a JS ML runtime) and the historical export from ml-feature-store; the orchestrator can land the pipeline + report, but an operator provisions compute and reviews the backtest before ml-serve-aiscore ships. intelligence-api needs an API-key issuance + billing decision.
  - DB migrations + edge functions apply to Supabase project qlzsnuspiypyejaqcdad via MCP/CLI; if the orchestrator lacks write access an operator applies files under racefeed/supabase/migrations/ + racefeed/supabase/functions/.
  - responsible-gaming-suite touches EVERY bet submit RPC — treat as high-risk; legal/compliance sign-off recommended before enabling limits/age/region in a real market. This is also the gate that unlocks marketing in restricted channels/regions.
  - realtime-sockets: double-check the Realtime publication never includes races.winner / race_runners.finish_pos before enabling.
  - creator-duets requires a content-moderation decision (automated + human queue) and storage cost/abuse review before public posting is enabled.
  - churn-winback + tentpole-event-mode + live-stakes push all send notifications — confirm APNs/push creds and honor RG self-exclusion + quiet hours.
  - Device/visual QA after merge: model-backed intel sanity, realtime pool updates, RG limit rejections, academy flow, event-mode UI, Android/web parity, creator capture/upload.
