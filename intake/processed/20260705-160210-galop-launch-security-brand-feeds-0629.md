PROJECT: galop

# Fifth batch — LAUNCH READINESS: security hardening, branding alignment, and
# real live-feed ingestion. Security tasks are launch-blocking and material
# (route to human approval). Findings from a live audit of Supabase project
# qlzsnuspiypyejaqcdad on 2026-06-29. Do the security block FIRST.

- id: sec-lock-operator-tables
  title: LAUNCH-BLOCKER — enable RLS + revoke anon/authenticated on operator_api_keys, webhook_deliveries, health_log
  material: yes
  model: sonnet
  depends: []
  proof: live SQL on qlzsnuspiypyejaqcdad shows relrowsecurity=true AND has_table_privilege('anon',t,'select|insert|update|delete')=false for all of operator_api_keys, webhook_deliveries, health_log
  prompt: |
    AUDIT FINDING (critical): public tables operator_api_keys, webhook_deliveries, and
    health_log have RLS DISABLED and full SELECT/INSERT/UPDATE/DELETE/TRUNCATE granted to
    anon AND authenticated. The app ships the anon key, so anyone can read operator API key
    hashes (key_hash/key_prefix/last_used_ip) and insert/delete/truncate these tables.
    Migration: for each of these three tables — `alter table ... enable row level security;`
    `revoke all on public.<t> from anon, authenticated;` and grant only what service_role /
    the operator edge functions genuinely need (service_role bypasses RLS). Add no anon/
    authenticated policy (deny by default). Sweep for any OTHER public table with RLS
    disabled + anon/authenticated grants and lock those too. Apply to qlzsnuspiypyejaqcdad.
    Acceptance: the three tables have RLS on and zero anon/authenticated table privileges;
    no other RLS-disabled public table is anon-writable.

- id: sec-revoke-anon-write-functions
  title: LAUNCH-BLOCKER — revoke anon execute on grant_entitlement, *_wl, and bare settle_* functions
  material: yes
  model: sonnet
  depends: []
  proof: live SQL on qlzsnuspiypyejaqcdad shows has_function_privilege('anon', fn, 'execute')=false for grant_entitlement, place_pool_bet_wl, cash_out_bet_wl, settle_exotics(), settle_multis(), settle_resolved_races(), settle_contest()
  prompt: |
    AUDIT FINDING (critical, broken access control): these SECURITY DEFINER functions are
    anon-executable — grant_entitlement(p_operator,p_player,p_tier,p_days) (anyone can grant
    premium), place_pool_bet_wl / cash_out_bet_wl (take a p_player param instead of auth.uid()
    → act as ANY player), and settle_exotics()/settle_multis()/settle_resolved_races()/
    settle_contest() (anyone can trigger payouts). Migration: `revoke execute on function ...
    from anon, public;` for each; the operator-facing ones (_wl, grant_entitlement) should be
    `to service_role` only (they are called by the operator edge function with the service
    key); the settle_* should be service_role only. Then AUDIT every public SECURITY DEFINER
    function's grants and revoke anon on any that write/settle/pay/grant (leave read-only
    ones like rf_pool_state/rf_live_field_feed/rf_runner_intel anon). Do NOT touch the
    correctly-scoped consumer RPCs (rf_submit_win/exotic/group/acca use auth.uid() + are
    authenticated-only). Apply to qlzsnuspiypyejaqcdad. Acceptance: the listed functions are
    not anon-executable; consumer bet RPCs still work for authenticated users.

- id: sec-env-secret-hygiene
  title: LAUNCH-BLOCKER — untrack .env, gitignore it, rotate CRON_SECRET
  material: yes
  model: haiku
  depends: []
  proof: `cd racefeed && git ls-files --error-unmatch .env` returns non-zero (untracked) AND `.env` matches a line in .gitignore
  prompt: |
    AUDIT FINDING: racefeed/.env is TRACKED in git and contains CRON_SECRET (a real secret
    that gates cron endpoints), plus the Supabase URL/anon key and PostHog key (those are
    public-by-design, but CRON_SECRET is not). Fix: `git rm --cached racefeed/.env`, add
    `.env` (and keep `.env*.local`) to racefeed/.gitignore, commit. Then ROTATE CRON_SECRET
    (generate a new value) and move it to the Vercel/Supabase environment only — never
    committed. Provide a racefeed/.env.example with placeholder keys for onboarding.
    Acceptance: .env is untracked + gitignored; .env.example exists; (operator rotates the
    secret in the hosting env — see OPERATOR).

- id: sec-rls-policy-audit
  title: Add read-own policies to user-facing RLS-enabled-no-policy tables (or confirm lockdown)
  material: yes
  model: sonnet
  depends: [sec-lock-operator-tables]
  proof: live SQL on qlzsnuspiypyejaqcdad shows every user-facing table (wallet_balances, wallet_transactions, player_ratings, player_entitlements, streak_state, contest_entries, redemption_requests) either has a read-own RLS policy or is confirmed definer-RPC-only, and none are anon-readable
  prompt: |
    AUDIT FINDING: 14 public tables have RLS ENABLED but NO POLICY (deny-all): agent_audit,
    ai_cache, ai_usage, console_audit_log, contest_entries, feed_impressions,
    operator_sessions, operators, player_entitlements, player_ratings, redemption_requests,
    streak_state, wallet_balances, wallet_transactions. Deny-all is safe but may be a
    functional gap. For each USER-FACING table, add a `for select using (auth.uid() =
    user_id)` read-own policy (and writes via definer RPC only); for internal/ops tables,
    confirm the intentional lockdown and leave as-is. Do not broaden anything to anon. Apply
    to qlzsnuspiypyejaqcdad. Acceptance: user-facing tables are readable by their owner only;
    internal tables remain locked; nothing is anon-readable.

- id: sec-definer-search-path
  title: Ensure all SECURITY DEFINER functions set search_path (advisor: function_search_path_mutable)
  material: yes
  model: sonnet
  depends: []
  proof: live SQL on qlzsnuspiypyejaqcdad shows no public SECURITY DEFINER function has a NULL proconfig search_path
  prompt: |
    Harden against search_path hijacking. Find every public SECURITY DEFINER function whose
    proconfig lacks a `search_path` setting (`select proname from pg_proc where prosecdef and
    (proconfig is null or not exists(select 1 from unnest(proconfig) c where c like
    'search_path=%'))`) and add `set search_path = public, pg_temp` via CREATE OR REPLACE
    (or ALTER FUNCTION ... SET search_path). The rf_* functions added this cycle already do
    this — fix the legacy ones. Apply to qlzsnuspiypyejaqcdad. Acceptance: zero definer
    functions with a mutable search_path.

- id: sec-rate-limit-bets
  title: Per-user rate limiting / abuse guards on consumer bet submit RPCs
  material: yes
  model: sonnet
  depends: [sec-revoke-anon-write-functions]
  proof: `cd racefeed && npm test` passes AND live SQL on qlzsnuspiypyejaqcdad shows a rapid burst of rf_submit_win calls from one user is throttled (e.g. Nth call in a short window raises/records a rate-limit)
  prompt: |
    Prevent economy/spam attacks at launch. Add a lightweight per-user rate limit to the
    consumer submit RPCs (rf_submit_win/exotic/group/acca and any pool join): a small
    counter table or a check against created_at of the user's recent bets, rejecting more
    than N submits per rolling window (config constant). Keep it inside the definer RPC so
    it can't be bypassed. Apply to qlzsnuspiypyejaqcdad. Acceptance: a burst beyond the cap
    is rejected with a clear error; normal play is unaffected; consumer flows still pass.

- id: brand-app-identity
  title: Align app identity from "RaceFeed" to the canonical brand (Galop) — app.json, logo, scheme, bundle
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND grep shows app.json name/scheme + BrandLogo wordmark use the canonical brand and no user-facing "RaceFeed" string remains
  prompt: |
    AUDIT FINDING: the app ships as "RaceFeed" (app.json name "RaceFeed", slug "racefeed",
    scheme "racefeed", bundleIdentifier com.kalepasch1.racefeed) and components/BrandLogo.tsx
    says "RaceFeed brand logo", but the product brand everywhere else is "Galop" (folder,
    docs, in-app "You vs Galop AI"). Make identity consistent to the CANONICAL name the
    operator confirms (default: Galop). Update app.json name + scheme (deep links) +
    BrandLogo wordmark/comment + any user-facing "RaceFeed" copy + README + web title/favicon
    alt. IMPORTANT: bundleIdentifier/package + scheme changes affect deep links, push, and
    store identity — flag for operator confirmation (see OPERATOR) and DO NOT change the
    bundle id without their explicit yes; default to keeping the bundle id and only changing
    display name/scheme/wordmark if they prefer. Acceptance: tsc 0; no user-facing "RaceFeed"
    string; logo + app name reflect the canonical brand.

- id: brand-copy-consistency
  title: Consistent Galop voice across UI copy, empty states, share card, store metadata
  material: no
  model: sonnet
  depends: [brand-app-identity]
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes
  prompt: |
    Sweep in-app copy for a consistent brand voice: tab labels, empty states, flash toasts,
    the RewardsHud, the share-result card wordmark, onboarding, and a drafted App Store /
    Play listing (title, subtitle, description, keywords) — all "Galop", one tone
    (confident, AI-forward, playful-but-trustworthy; coins-only skill framing, not gambling).
    Add the store copy under racefeed/store-listing/. Do not change functionality.
    Acceptance: tsc 0; copy is on-brand and consistent; store-listing draft exists.

- id: feed-racing-api-ingest
  title: Wire The Racing API (real racecards/odds/results) into ingestion + resolver
  material: yes
  model: opus
  depends: []
  proof: live check on qlzsnuspiypyejaqcdad shows a real racecard (race + full field with real horses/odds) ingested into races/race_runners AND its result resolved via the near-live resolver, end-to-end, winner-free until off-time
  prompt: |
    Make the data real. Wire The Racing API (theracingapi.com) into the existing edge
    functions racefeed/supabase/functions/ingest-races, ingest-race-data, and
    resolve-results: pull today's racecards (UK/IRE on the free/standard tier) into races +
    race_runners (map runners to the full field; keep the featured a/b for the legacy path),
    pull odds updates, and pull results into rf_record_finish -> the near-live resolver ->
    rf_settle_* . Store the API key from the edge env (never committed). Keep the winner-free
    posture: finish_pos/winner only after off-time/resolution. Decouple video: real races use
    real DATA but keep feed_clip_url from the demo_clips pool until a video-rights deal lands
    (see OPERATOR). Apply/deploy to qlzsnuspiypyejaqcdad. Acceptance: a real UK/IRE race
    appears in the feed with real runners+odds, bets settle from the real result, no result
    leak pre-off.

- id: feed-betfair-odds
  title: (Optional) Betfair Exchange live odds -> market movers / steamers / in-running
  material: yes
  model: sonnet
  depends: [feed-racing-api-ingest]
  proof: live check on qlzsnuspiypyejaqcdad shows live exchange odds populating the market-move/steamer signal for at least one live race (winner-free)
  prompt: |
    Add live market tension. Integrate the Betfair Exchange API (live prices + traded
    volume) via an edge function to feed drifting odds + the steamer/drifter market_move
    signal used by rf_runner_intel and the in-running surfaces. Requires a Betfair app key
    (see OPERATOR — the LIVE key has a one-time fee; the DELAYED key is free and fine to
    start). Map exchange prices to the existing odds fields; keep winner-free. Apply/deploy
    to qlzsnuspiypyejaqcdad. Acceptance: live/exchange-derived odds move on at least one race
    and drive the market-move signal; no result leak.

OPERATOR:
  - APPLY THE SECURITY BLOCK THIS WEEK (pre-launch). The three critical DB fixes
    (sec-lock-operator-tables, sec-revoke-anon-write-functions, sec-definer-search-path) are
    material migrations on prod qlzsnuspiypyejaqcdad — approve the orchestrator merge, or ask
    the session to apply them immediately (they are low-risk lockdowns of access that should
    never have been public). Verify the operator/white-label edge functions still work
    afterward (they use the service key, so they should).
  - ROTATE CRON_SECRET after sec-env-secret-hygiene lands, in the Vercel + Supabase env only
    (assistant cannot enter secrets). Also rotate anything else that was in the committed
    .env if the repo is or will be public. Consider Supabase leaked-password protection +
    enforcing a min TLS + Postgres upgrade if the advisor flags them.
  - BRAND NAME DECISION (brand-app-identity): confirm the canonical name is "Galop" (or
    other) and whether to change the iOS/Android bundle id + Expo slug now (cleaner pre-
    launch) or keep com.kalepasch1.racefeed to avoid store re-provisioning. This blocks the
    branding tasks.
  - LIVE DATA (feed-racing-api-ingest): create a The Racing API account and provide the key
    in the Supabase edge env. Free/Standard tier covers UK & IRE racecards + results (updates
    ~every 3 min); AUS/USA are higher tiers. This gives real fields/odds/results now.
  - LIVE ODDS (feed-betfair-odds): decide on Betfair — a Betfair account + Application Key is
    required; the live-data key carries a one-time fee, the delayed key is free. Optional for
    launch.
  - LIVE VIDEO: there is no free, legal live horse-racing video feed. For real live video you
    need a commercial rights deal (e.g. SIS, Racecourse Media Group / Racing TV, At The
    Races / Sky Sports Racing) — a business/licensing step, not code. Launch plan: ship real
    DATA + representative public-domain replay VIDEO (clearly labelled), with the feed already
    decoupling clip from data, until a video deal lands. Confirm you're comfortable labelling
    footage as representative for launch.
