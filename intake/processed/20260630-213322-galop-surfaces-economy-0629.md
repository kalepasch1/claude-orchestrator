PROJECT: galop

# Third batch — ambient surfaces, social economy, integrity, personalization,
# growth, engine reuse, infra. Independent of galop-0629.md and
# galop-social-ai-0629.md. Dependencies below are WITHIN this file only; external
# prereqs are noted in prose. Several tasks are native/infra-heavy — their proof
# is the JS/bridge layer + typecheck; device/native build verification is listed
# under OPERATOR.

- id: live-activity-running-race
  title: iOS Live Activity / Dynamic Island for a running race + open bet
  material: yes
  model: opus
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npx expo config --type prebuild` succeeds with the Live Activity config plugin present
  prompt: |
    When a user has an open bet on a race that is running, show a Live Activity (lock
    screen + Dynamic Island) with the running clock (feed_duration_seconds), the horse,
    and a live cash-out value. Add the iOS Widget/Live Activity extension via an Expo
    config plugin (ActivityKit), a JS bridge module (hooks/useLiveActivity.ts) to
    start/update/end the activity, and wire start on bet-place (components/feed/BetSlip.tsx
    single win path) + update on the running clock + end on settle. Updates pushed via
    APNs Live Activity tokens (reuse push infra). Keep winner-free: the activity shows
    time + static-odds-derived cash-out only, never finish_pos. Acceptance: tsc 0; config
    plugin present and prebuild resolves; bridge start/update/end functions exist and are
    called from the bet + clock + settle paths. (Device render verified by operator.)

- id: home-screen-widget
  title: Home-screen widget — next race countdown + open bets / today P&L
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npx expo config --type prebuild` succeeds with the widget config plugin present
  prompt: |
    Add a WidgetKit home-screen widget showing the next featured race countdown and the
    user's open-bet count + today's coin P&L. Provide the data via an App Group shared
    store written from JS (hooks/useWidgetData.ts) on feed refresh + bet settle, and an
    Expo config plugin for the widget extension. Acceptance: tsc 0; config plugin +
    App Group present; JS writes the shared payload on the right events. (Native render
    verified by operator.)

- id: peer-parimutuel-pools
  title: Player-vs-player pari-mutuel pools on a race (clan/jackpot)
  material: yes
  model: opus
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes AND live SQL check on Supabase project qlzsnuspiypyejaqcdad shows tables peer_pools + peer_pool_entries and rf_pool_join / rf_pool_settle exist, RLS read-own-or-public, submit RPC execute granted to authenticated only
  prompt: |
    Turn the economy social: let users create a coin pool on a race that everyone rides
    together, pot split by result. New migration: peer_pools(id, race_id, creator_id,
    leg_type, rake_bps, status, created_at) + peer_pool_entries(pool_id, user_id,
    runner_no, stake) with RLS (read pools you're in or public; entries read-own).
    rf_pool_join(p_pool_id, p_runner_no, p_stake) deducts coins + records an entry
    (authenticated). rf_pool_settle(p_race_id) (service_role) grades vs finish_pos and
    splits the net pot pari-mutuel across winning entries. Apply to qlzsnuspiypyejaqcdad
    (grants: join->authenticated, settle->service_role). Add hooks/usePeerPools.ts + a
    minimal UI to create/join/see a pool from the race card. Reuse existing pool/rake
    patterns if present. Winner-free pre-resolution. Acceptance: join deducts + records;
    settle splits the pot correctly to winners; RLS prevents cross-user entry reads.

- id: ranked-seasons-mmr
  title: Skill-rating ladder (calibrated MMR) with seasons + divisions
  material: yes
  model: opus
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes AND live SQL check on qlzsnuspiypyejaqcdad shows table skill_ratings + rf_rate_pick exist, RLS read-own, RPC service_role-only for rating updates
  prompt: |
    Reframe the app as a skill esport. Add a calibrated rating that moves on pick quality
    (Brier-style: reward backing higher-than-market true probability, not just wins). New
    migration: skill_ratings(user_id, rating, season, division, picks, updated_at) +
    rf_rate_pick(p_user_id, p_race_id, p_runner_no) settle hook (service_role) that
    updates rating from the realized result vs the pre-race implied prob. Seasonal reset
    + division tiers (bronze..champion). Apply to qlzsnuspiypyejaqcdad. Surface rating +
    division in profile and RewardsHud; add a ranked leaderboard view. Winner-free input.
    Acceptance: a resolved pick adjusts rating in the right direction; seasons/divisions
    compute; RLS read-own for ratings.

- id: provable-fairness-badge
  title: Surface commit-reveal provable fairness on resolved races
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND live SQL check on qlzsnuspiypyejaqcdad shows a definer view/RPC exposing result_commit pre-race and result_salt only for resolved races (never the live winner), granted to anon+authenticated
  prompt: |
    Make integrity visible. races already carry result_commit/result_salt/commit_at. Add
    a winner-free-safe path: a definer view or RPC rf_fairness(p_race_id) that returns
    result_commit + commit_at always, and result_salt + the revealed result ONLY when
    races.status='resolved' (mirror the race_finish_public pattern). Grant anon+
    authenticated. Apply to qlzsnuspiypyejaqcdad. Add a "Verify result" affordance on
    settled cards that recomputes the hash from the revealed salt+result and shows it
    matches the pre-committed commit. Acceptance: pre-resolution the salt/result are never
    exposed; post-resolution the client verification matches the commit.

- id: bandit-feed-ranking
  title: Contextual-bandit personalized feed ranking with exploration
  material: yes
  model: opus
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes AND live SQL check on qlzsnuspiypyejaqcdad shows rf_live_field_feed still returns the winner-free shape and a per-user preference store exists
  prompt: |
    Make the feed learn each user. Add a per-user preference store (race_type / odds-band
    / bet-style weights) updated from engagement + bet events (a table + an update RPC or
    a periodic job). Evolve rf_live_field_feed ordering to score eligible races by those
    weights with an exploration term (epsilon or UCB), keeping live-first + per-user
    jitter + winner-free output. Feed engagement signals from lib/analytics events
    (watch time, bet placed) via a lightweight writer. Apply schema to qlzsnuspiypyejaqcdad.
    Acceptance: feed order shifts toward a user's demonstrated preferences while still
    exploring; output stays winner-free and shape-identical to today.

- id: per-user-edge-rpc
  title: Personal edge report (where the user is +EV vs leaking)
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND live SQL check on qlzsnuspiypyejaqcdad shows rf_user_edge() returns per-segment ROI and execute granted to authenticated only (read-own)
  prompt: |
    Build expertise loyalty. New RPC rf_user_edge() — security definer, auth.uid()-scoped,
    aggregates the caller's settled bets (exotic_bets/group_bets/acca_bets) into ROI +
    hit-rate by segment (bet type, race type, odds band) and returns the best/worst
    segments. Grant authenticated (returns own data only). Apply to qlzsnuspiypyejaqcdad.
    Surface a weekly "edge report" card (where you're +EV, where you leak) in profile and
    as an occasional feed chapter. Acceptance: ROI math matches a hand check on a sample
    user; only own data is returned.

- id: guest-first-bet-onboarding
  title: Sub-30s cold start — guest into the feed, first bet before signup
  material: yes
  model: opus
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes AND live check shows anonymous sign-in is enabled and a guest can hold a coin_balances row under RLS, with an upgrade-to-account path that preserves balance
  prompt: |
    Cut time-to-first-magic. Use Supabase anonymous auth so a new user lands directly in
    the feed with starter coins and can place a first bet before any signup; convert to a
    real account afterwards (link identity, preserve coin_balances + streak + bets). Adjust
    app/(auth) flow + app/_layout to allow guest entry, ensure RLS policies cover anon
    users' own rows, and add an "save your account" upsell after the first win. Apply any
    policy/migration to qlzsnuspiypyejaqcdad. Acceptance: a fresh install reaches a placed
    bet without signup; upgrading to an account keeps balance/history; RLS still isolates
    per-user data.

- id: referral-shared-stakes
  title: Referral loop rewarding a shared betting moment
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND `npm test` passes AND live SQL check on qlzsnuspiypyejaqcdad shows referrals table + rf_redeem_referral exist, RLS read-own, RPC execute granted to authenticated only with anti-abuse guards
  prompt: |
    Build a contextual referral loop. New migration: referrals(code, inviter_id,
    invitee_id, status, reward_granted, created_at) + rf_redeem_referral(p_code) that, on a
    new (or guest-upgraded) user redeeming, grants BOTH users a shared reward (e.g. a free
    pre-built joint parlay on tonight's card) with anti-abuse guards (one redemption per
    invitee, no self-referral, rate-limited). Apply to qlzsnuspiypyejaqcdad. Add invite UI
    + deep-link handling (expo-linking) and reflect status in profile. Acceptance: a
    redeemed code grants both sides once; self/duplicate referrals are rejected; RLS
    read-own.

- id: embeddable-race-widget-api
  title: Public read-only "race of the day" embeddable card + API
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND a live check shows a public, winner-free, rate-limited endpoint returns a featured race + field (no finish_pos)
  prompt: |
    Distribution beyond the app store. Add a public, winner-free, rate-limited endpoint
    (Supabase edge function under racefeed/supabase/functions/) returning the featured
    "race of the day" + field (reuse rf_live_field_feed shape; NEVER finish_pos/winner)
    and a tiny embeddable HTML/JS card that renders it with a deep-link CTA into the app.
    Apply/deploy the function to qlzsnuspiypyejaqcdad. Acceptance: the endpoint is public +
    rate-limited + winner-free; the embed renders a race card with a working app deep link.

- id: edge-cache-feed
  title: Edge-cache the feed + intel and precompute silks (latency + cost)
  material: yes
  model: sonnet
  depends: []
  proof: `cd racefeed && npx tsc --noEmit` exits 0 AND a live check shows cached responses for rf_live_field_feed/rf_runner_intel are served with a short TTL and the client falls back cleanly on miss
  prompt: |
    Make the scroll instant and cheap at scale. Put a short-TTL edge cache in front of the
    feed + intel reads (Supabase edge function or cache headers / a CDN layer) keyed by
    user bucket so per-user DB cost drops and the scroll never stalls; precompute/serve
    silk colours (components/feed/silks.ts is deterministic — can be a static map). Ensure
    cache is winner-free and invalidates on race status change. Client uses the cached path
    with a clean fallback to the direct RPC on miss/stale. Apply any function to
    qlzsnuspiypyejaqcdad. Acceptance: cached responses serve within TTL; status changes
    invalidate; no winner leak; fallback works.

OPERATOR:
  - Native extensions (live-activity-running-race, home-screen-widget) require an Expo prebuild + EAS native build and Apple entitlements (App Groups, ActivityKit/WidgetKit, APNs Live Activity push). The orchestrator can land the JS + config-plugin layer; an operator must run the native build and verify on a device. An Apple Watch glance was considered and deferred (high native cost, low near-term ROI).
  - DB migrations + edge functions apply to Supabase project qlzsnuspiypyejaqcdad via MCP/CLI. If the orchestrator lacks write access, an operator applies the migration files under racefeed/supabase/migrations/ and functions under racefeed/supabase/functions/ for the material tasks (peer-parimutuel-pools, ranked-seasons-mmr, provable-fairness-badge, bandit-feed-ranking, per-user-edge-rpc, guest-first-bet-onboarding, referral-shared-stakes, embeddable-race-widget-api, edge-cache-feed).
  - guest-first-bet-onboarding requires enabling Supabase Anonymous Sign-Ins in the project Auth settings (operator toggle) before it works.
  - coin-staking / "back a tipster" and multi-sport engine expansion were considered but deferred: staking depends on the tipster-profile work from galop-social-ai-0629.md (copy-tipster-roi) landing first; multi-sport is a large data/ingestion program better scoped as its own intake once a real live data provider is wired.
  - Device/visual QA after merge: Live Activity + widget render, peer-pool create/join/settle feel, ranked ladder, guest→account upgrade, referral deep links.
