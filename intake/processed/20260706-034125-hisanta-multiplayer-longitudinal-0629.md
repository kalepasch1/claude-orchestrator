PROJECT: hisanta

# HiSanta — Phase 5: multiplayer/live learning + longitudinal intelligence.
# Builds on Phase 1 (LIVE Supabase `santas-secret-workshop`, ref whhfugddqehxxbmwutsw), Phase 2/3/4 intake files.
# Cross-file deps by id: capture-live-migrations, le-item-responses.
# Reuse live tables: coop_quests/coop_participants, child_connections, family_circle, consent_edges
#   (+ app_has_consent; feature 'peer_teach'), child_preference_profiles, child_lesson_mastery, notification_queue,
#   spark_ledger, game_sessions, wellbeing_settings.
# RLS: guardian via children.guardian_id/co_guardian_id=auth.uid(); family read via family_circle. Helper fns
#   app_is_guardian_of/app_can_access_child stay anon+authenticated EXECUTE-able. Privileged DEFINER fns guard
#   `if auth.uid() is not null and <unauthorized> then raise`; anon EXECUTE revoked. Sparks never money-redeemable.
# Cross-child interaction is asynchronous/recorded/adult-visible by default and requires consent on BOTH sides;
#   no open private messaging for under-13s. Honor wellbeing caps on anything child-facing.
# DB tasks ship pgTAP (gate `supabase test db`); jobs/algorithms ship colocated tests (gate `deno test -A <path>`).
# Agents: `supabase db reset` first; inspect repo before editing.

- id: coop-learning-rooms
  title: Synchronous co-op learning rooms with rotating roles (consent-gated)
  material: yes
  model: opus
  depends: [capture-live-migrations]
  proof: `supabase test db` exits 0 (supabase/tests/coop_rooms_test.sql)
  prompt: |
    Let 2-4 consented kids solve a shared challenge together in real time (live protégé effect). Migration
    supabase/migrations/0037_coop_rooms.sql:
    - learning_rooms (id, host_child_id, skill, coop_quest_id null, status text check in
      ('lobby','active','done','cancelled'), max_players int default 4, created_at).
    - room_participants (id, room_id fk, child_id fk, role text check in ('guide','solver','checker'),
      joined_at, unique(room_id,child_id)).
    - join_room(p_room,p_child) DEFINER fn: admits a child ONLY if there is an approved child_connections edge to
      an existing member AND app_has_consent(p_child,'peer_teach') AND app_has_consent(host,'peer_teach') AND the
      room isn't full; assigns a role. rotate_roles(p_room) cycles roles. On room completion, credit each
      participant via spark_ledger (source_type 'teamwork' for guide/checker, 'peer_teach' for solver-help).
    - RLS: family of any participant may read; writes auth.uid() not null.
    pgTAP supabase/tests/coop_rooms_test.sql: joining without a connection OR without consent throws; a full room
    rejects a 5th; rotate_roles reassigns; completion credits each participant exactly once. (Realtime channel
    wiring is app-side; this task covers schema + authorization + scoring.)

- id: live-family-game-night
  title: Scheduled cross-household family game night on the room infra
  material: yes
  model: sonnet
  depends: [coop-learning-rooms]
  proof: `supabase test db` exits 0 (supabase/tests/family_game_night_test.sql)
  prompt: |
    Turn family_circle into a weekly ritual (retention + relative engagement). Migration
    supabase/migrations/0038_family_game_night.sql: game_nights (id, child_id, scheduled_at, room_id null, status,
    created_at) and schedule_game_night() (guardian) that, at creation, enqueues notification_queue reminders to all
    active family_circle members across households and, at start, spins up a learning_rooms row whose participants may
    include adult family members. join is limited to active family_circle members (+ the child). pgTAP
    supabase/tests/family_game_night_test.sql: scheduling queues one reminder per active family member; a non-family
    user cannot join; starting creates exactly one linked room. (pg_cron for start/reminders = OPERATOR.)

- id: lifelong-learner-model
  title: Persistent, portable, parent-owned model of how THIS child learns
  material: yes
  model: opus
  depends: [capture-live-migrations, le-item-responses]
  proof: `supabase test db` exits 0 (supabase/tests/lifelong_model_test.sql)
  prompt: |
    Make switching cost "you'd lose everything the app understands about my kid." Migration
    supabase/migrations/0039_lifelong_learner_model.sql:
    - learner_model (child_id pk fk children, modality_profile jsonb, pace_profile jsonb, motivators jsonb,
      updated_at) consolidated from child_preference_profiles + child_lesson_mastery + item_responses + bandit history.
    - export_learner_model(p_child) DEFINER fn (guardian only) returning a parent-owned portable JSON artifact
      (no other child's data, no legal name) and writing an audit_log row.
    - seed_sibling_prior(p_from_child,p_to_child) DEFINER fn (same-guardian only) that initializes a new sibling's
      learner_model as a prior from an existing child's model, gated on guardian ownership of BOTH.
    - RLS family read; guardian write.
    pgTAP supabase/tests/lifelong_model_test.sql: export is guardian-only and contains no cross-family ids; sibling
    seeding requires the same guardian on both children and copies the prior; a non-guardian export throws.

- id: predictive-intervention
  title: Forecast disengagement/stall and prompt the parent with ONE pre-emptive action
  material: yes
  model: opus
  depends: [le-item-responses]
  proof: `deno test -A supabase/functions/predict-intervention/index.test.ts` exits 0
  prompt: |
    Shift retention from reactive to predictive. Build supabase/functions/predict-intervention/index.ts: from each
    child's recent trajectory (accuracy trend, latency drift, session cadence, frustration signals, upcoming
    forgetting-curve due items) score risk of (a) disengagement/churn and (b) hitting a skill wall; when risk crosses
    a threshold, enqueue ONE concrete parent action into notification_queue (e.g. "Mia's stuck on regrouping — try this
    5-min game, or have Grandpa record it"), never a guilt/streak-shame message. Schedule daily (pg_cron migration).
    index.test.ts on fixtures: a declining/stalling trajectory produces exactly one actionable parent nudge; a healthy
    trajectory produces none; the message contains a concrete next step and no shaming language. (Deploy/cron = OPERATOR.)

OPERATOR:
  - Approve + apply each material migration to prod Supabase `santas-secret-workshop` (ref whhfugddqehxxbmwutsw) after merge.
  - Deploy edge function predict-intervention and enable pg_cron/pg_net; wire pg_cron for family-game-night start + reminders.
  - Provision the app-side realtime channel (Supabase Realtime) for coop-learning-rooms and family-game-night presence.
  - Confirm COPPA posture for cross-child live rooms (recorded/adult-visible default, both-sides consent, no open messaging) and for the portable learner-model export/retention.
