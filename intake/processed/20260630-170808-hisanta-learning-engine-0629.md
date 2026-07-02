PROJECT: hisanta

# HiSanta — Phase 3: the closed-loop causal learning engine.
# These five workstreams are ONE loop, not five features. Build order matters; depends enforce it:
#   IRT-calibrated diagnostic items  ->  expose specific misconceptions  ->  which are causal nodes
#   in a prerequisite DAG  ->  a causal contextual bandit optimizes against misconception-extinction
#   rewards (with an auditable efficacy ledger + ethical guardrails)  ->  the policy is distilled onto
#   on-device models that run it in real time and feed federated signal back into calibration+discovery.
#
# Builds on Phase 1 (LIVE in Supabase `santas-secret-workshop`, ref whhfugddqehxxbmwutsw) and Phase 2
# (intake/hisanta-0629.md). Cross-file deps referenced by id: capture-live-migrations, transfer-item-generator,
# teachback-scoring, swarm-distillation-job, wellbeing-enforcement.
# Live objects to reuse: child_lesson_mastery (mastery_prob/durable/variant_history/next_review_at),
#   learning_item_variants, bandit_arms, strategy_registry, recommend_arm(), record_retrieval(),
#   wellbeing_settings, peer_teach_sessions.teachback_media_url, ai_interactions.
# RLS convention: guardian via children.guardian_id/co_guardian_id=auth.uid(); family read via family_circle.
#   Helper fns app_is_guardian_of/app_can_access_child stay anon+authenticated EXECUTE-able (policies call them).
#   Privileged DEFINER fns: guard `if auth.uid() is not null and <unauthorized> then raise`; anon EXECUTE revoked.
# Every DB task ships a pgTAP test in supabase/tests/ (gate: `supabase test db`). Every job/algorithm ships a
#   colocated test (gate: `deno test -A <path>`). Agents: `supabase db reset` first; inspect repo before editing.
# ETHICS: any task that selects what a child sees must honor the no-harm floor + consent + review register
#   defined in le-experimentation-guardrails. Do not deploy experimentation arms without it.

# ---------- FOUNDATION ----------

- id: le-item-responses
  title: Per-item response log (the substrate IRT, misconceptions, and causal inference all read)
  material: yes
  model: opus
  depends: [capture-live-migrations]
  proof: `supabase test db` exits 0 (supabase/tests/item_responses_test.sql)
  prompt: |
    The engine has mastery state but no item-level response log; IRT/misconception/causal layers all need it.
    Migration supabase/migrations/0021_item_responses.sql:
    - Create item_responses (id, child_id fk children, item_id fk learning_item_variants, skill text,
      correct boolean, chosen_distractor text null, latency_ms int null, ability_at_attempt numeric null,
      was_delayed boolean default false, presented_at timestamptz, created_at default now()). Index by
      (skill, created_at) and (child_id, skill). RLS: family read via app_can_access_child; insert auth.uid() not null.
    - Extend record_retrieval(p_child,p_skill,p_correct,p_variant_id) to ALSO insert an item_responses row
      (was_delayed = (next_review interval was due)). Keep DEFINER guard + existing mastery logic untouched.
    pgTAP supabase/tests/item_responses_test.sql: calling record_retrieval inserts exactly one response row with
    matching child/skill/correct; RLS blocks a non-family select.

# ---------- WORKSTREAM 5: IRT CALIBRATION ----------

- id: le-irt-calibration
  title: 2-PL/3-PL item calibration from response data (empirical-Bayes)
  material: yes
  model: opus
  depends: [le-item-responses]
  proof: `deno test -A supabase/functions/irt-calibrate/index.test.ts` exits 0
  prompt: |
    Migration supabase/migrations/0022_item_parameters.sql: create item_parameters (item_id pk fk
    learning_item_variants, skill, a numeric default 1 [discrimination], b numeric default 0 [difficulty],
    c numeric default 0 [guessing], n_responses int default 0, dim_loadings jsonb default '{}', updated_at).
    RLS read true; write auth.uid() not null. Build edge function supabase/functions/irt-calibrate/index.ts that
    reads item_responses, fits 2-PL (optionally 3-PL) parameters per item via marginal MLE / EM with
    empirical-Bayes shrinkage toward the skill mean for low-n items, and upserts item_parameters. Schedule
    nightly (pg_cron migration; create-extension-guarded). index.test.ts: on a synthetic response set generated
    from known b values, recovered b ordering matches ground truth (Spearman >= 0.9) and shrinkage pulls a
    1-response item toward the skill mean. (Deploy/cron = OPERATOR.)

- id: le-item-param-prediction
  title: Predict item parameters at generation time (zero cold-start), refine with data
  material: yes
  model: sonnet
  depends: [le-irt-calibration, transfer-item-generator]
  proof: `deno test -A supabase/functions/_shared/item_param_predict.test.ts` exits 0
  prompt: |
    Make synthetic items usable the instant they are generated. Add supabase/functions/_shared/item_param_predict.ts
    exporting predictParams(itemContent) -> {a,b,c} estimated from content features (skill, surface complexity,
    operand magnitude, distractor structure) — model-based or heuristic, documented. Wire transfer-item-gen and
    the variant generator to write predicted item_parameters on insert (n_responses=0). irt-calibrate already
    refines these as responses arrive (empirical Bayes). Colocated test: a freshly generated item gets non-null
    finite params; given two items where one is structurally harder, predicted b orders them correctly.

- id: le-adaptive-testing
  title: Computerized adaptive testing — measure ability in ~5 items, not 30
  material: no
  model: sonnet
  depends: [le-irt-calibration]
  proof: `deno test -A supabase/functions/_shared/cat.test.ts` exits 0
  prompt: |
    Add supabase/functions/_shared/cat.ts: selectNextItem(abilityEstimate, seenItems, skill) picks the unseen
    calibrated item maximizing Fisher information at the current ability; updateAbility(responses) does EAP/MLE
    ability estimation; stopRule(se, k) stops at target standard error or max items. Pure, no IO (takes
    item_parameters rows as input). cat.test.ts on a simulated learner of known ability: CAT reaches SE<=0.3 in
    <=8 items while a fixed random form needs materially more; ability estimate converges to true within tolerance.

# ---------- WORKSTREAM 2: MISCONCEPTION TAXONOMY ----------

- id: le-misconception-schema
  title: Misconceptions as first-class nodes + per-child extinction state
  material: yes
  model: sonnet
  depends: [capture-live-migrations]
  proof: `supabase test db` exits 0 (supabase/tests/misconception_schema_test.sql)
  prompt: |
    Migration supabase/migrations/0023_misconceptions.sql:
    - misconceptions (id, skill, label, description, remediation_ref text null, discovered boolean default false,
      created_at). RLS read true; write auth.uid() not null.
    - distractor_misconceptions (id, item_id fk learning_item_variants, distractor_key text, misconception_id fk).
    - child_misconception_state (id, child_id fk children, misconception_id fk, present boolean default true,
      extinguished boolean default false, consecutive_clear int default 0, last_seen_at, unique(child_id,misconception_id)).
      RLS family via app_can_access_child; write auth.uid() not null.
    pgTAP supabase/tests/misconception_schema_test.sql: a distractor maps to a misconception; child_misconception_state
    upsert is unique per (child,misconception); RLS blocks non-family select of child_misconception_state.

- id: le-misconception-discovery
  title: Unsupervised misconception discovery from wrong answers + teach-back transcripts
  material: yes
  model: opus
  depends: [le-item-responses, le-misconception-schema, teachback-scoring]
  proof: `deno test -A supabase/functions/misconception-discover/index.test.ts` exits 0
  prompt: |
    Build supabase/functions/misconception-discover/index.ts: cluster wrong-answer signatures (item_responses with
    chosen_distractor) together with teach-back transcript embeddings (from peer_teach_sessions) per skill; surface
    recurrent error clusters as candidate misconceptions; upsert misconceptions(discovered=true) and map the
    implicated distractors via distractor_misconceptions. Require a minimum cluster support before creating a node.
    Schedule nightly (pg_cron migration). index.test.ts on a fixture where two distinct systematic error patterns
    exist: exactly two misconception nodes are created, each linked to its distractors; random one-off errors below
    support do not create nodes; no child_id is written into a misconceptions row. (Deploy/cron/LLM-embeddings = OPERATOR.)

- id: le-diagnostic-distractors
  title: Generate misconception-tied distractors so every wrong answer is diagnostic
  material: yes
  model: sonnet
  depends: [le-misconception-schema, le-irt-calibration]
  proof: `deno test -A supabase/functions/_shared/diagnostic_distractors.test.ts` exits 0
  prompt: |
    Upgrade item generation so each item's wrong options are diagnostic. Add
    supabase/functions/_shared/diagnostic_distractors.ts: buildDistractors(skill, stem) returns >=2 distractors,
    each tagged with the misconception_id it would reveal, and a validator rejecting items whose distractors are
    not all mapped. Wire transfer-item-gen and the variant generator to persist distractor_misconceptions rows on
    insert. Colocated test: a generated subtraction item yields distractors each mapped to a real misconception
    (e.g. smaller-from-larger bug); the validator rejects an item with an unmapped distractor.

- id: le-misconception-reward
  title: Reward misconception extinction, not bare correctness, in the learning loop
  material: yes
  model: opus
  depends: [le-misconception-schema, le-item-responses]
  proof: `supabase test db` exits 0 (supabase/tests/misconception_reward_test.sql)
  prompt: |
    Make the optimization signal dense and sharp. Migration supabase/migrations/0024_misconception_reward.sql:
    - update_misconception_state(p_child, p_item, p_correct, p_distractor) DEFINER fn: a correct answer on an item
      that targets misconception M increments consecutive_clear and sets extinguished=true after a threshold of
      delayed-correct clears; choosing a misconception-tagged distractor sets present=true, extinguished=false,
      consecutive_clear=0. Guard with app_can_access_child.
    - Emit a learning-gain reward component for misconception extinction that the bandit reward consumes (write to
      bandit_arms.reward_sum via the existing reward path, or a reward_events row the bandit reads). A correct
      answer that leaves a known misconception un-cleared yields LESS reward than one that extinguishes it.
    pgTAP supabase/tests/misconception_reward_test.sql: distractor choice flips state to present; threshold of
    delayed clears sets extinguished; the extinction event produces a strictly larger reward than a plain correct.

# ---------- WORKSTREAM 1: CAUSAL PREREQUISITE DAG ----------

- id: le-skill-graph-schema
  title: Skill prerequisite graph + per-child ZPD frontier selector
  material: yes
  model: sonnet
  depends: [capture-live-migrations]
  proof: `supabase test db` exits 0 (supabase/tests/skill_graph_test.sql)
  prompt: |
    Migration supabase/migrations/0025_skill_graph.sql:
    - skill_edges (id, prereq_skill text, target_skill text, weight numeric default 0, causal boolean default false,
      method text, n int default 0, updated_at, unique(prereq_skill,target_skill)). RLS read true; write auth.uid() not null.
    - next_frontier_skills(p_child) DEFINER fn returning the child's zone of proximal development: target_skills whose
      prereqs (per skill_edges) are mastered (child_lesson_mastery.durable) but the target itself is not. Guard
      app_can_access_child. Also missing_foundation(p_child, p_skill) returning unmet upstream prereqs.
    pgTAP supabase/tests/skill_graph_test.sql: with A->B and A mastered/B not, frontier includes B; with A NOT
    mastered, frontier excludes B and missing_foundation(child,B) returns A.

- id: le-causal-prereq-inference
  title: Infer CAUSAL prerequisite edges (not correlational) from sequenced responses
  material: yes
  model: opus
  depends: [le-item-responses, le-skill-graph-schema]
  proof: `deno test -A supabase/functions/prereq-causal/index.test.ts` exits 0
  prompt: |
    Build supabase/functions/prereq-causal/index.ts: estimate whether mastering skill A causally accelerates mastery
    of B, exploiting the natural variation in sequencing already present in item_responses (e.g. difference-in-rates
    / matching on ability + age to deconfound, or instrumental variation from the bandit's exploration). Write
    skill_edges with causal=true, weight=effect size, method, n; demote edges that are merely correlational. Min-n gate.
    Schedule nightly (pg_cron migration). index.test.ts on synthetic data where A causally gates B and C merely
    correlates with B via shared age: A->B is written causal=true and C->B is not (or causal=false). (Deploy/cron = OPERATOR.)

- id: le-skill-embeddings-coldstart
  title: Zero-shot placement of new skills into the DAG via embeddings
  material: yes
  model: sonnet
  depends: [le-skill-graph-schema]
  proof: `deno test -A supabase/functions/_shared/skill_placement.test.ts` exits 0
  prompt: |
    A brand-new skill should inherit prerequisites before it has any response data. Add
    supabase/functions/_shared/skill_placement.ts: embed a skill from its descriptor, find nearest existing skills,
    and propose provisional skill_edges (causal=false, method='embedding_coldstart') above a similarity threshold,
    to be confirmed/demoted later by le-causal-prereq-inference. Colocated test: inserting a new fractions skill
    proposes prereqs from the nearest cluster above threshold and proposes none below it.

# ---------- WORKSTREAM 3: CAUSAL/UPLIFT LAYER ----------

- id: le-cate-uplift
  title: Heterogeneous treatment effects (CATE/uplift) per learner cluster
  material: yes
  model: opus
  depends: [swarm-distillation-job, le-item-responses]
  proof: `deno test -A supabase/functions/cate-uplift/index.test.ts` exits 0
  prompt: |
    Build supabase/functions/cate-uplift/index.ts: from logged arm assignments (bandit_arms / reward events) and
    learning-gain outcomes, estimate the conditional average treatment effect of each lever-arm PER anonymized
    learner-profile cluster (age band x dominant modality x struggling skill) using an uplift method (T-learner or
    causal forest). Write per-(cluster,lever,arm) effect + CI into strategy_registry.policy (no child identifiers).
    Schedule nightly. index.test.ts on synthetic data with known heterogeneous effects: recovered CATE signs and
    ordering per cluster match ground truth (rank corr >= 0.8); a no-effect cluster gets ~0. (Deploy/cron = OPERATOR.)

- id: le-causal-bandit
  title: Replace UCB with a Thompson contextual bandit seeded by CATE, with a no-harm floor
  material: yes
  model: opus
  depends: [le-cate-uplift, wellbeing-enforcement, le-experimentation-guardrails]
  proof: `supabase test db` exits 0 (supabase/tests/causal_bandit_test.sql)
  prompt: |
    Upgrade recommend_arm from UCB1 to a contextual Thompson-sampling bandit whose priors come from strategy_registry
    CATE estimates for the child's cluster. Keep the signature and DEFINER guard. Hard constraints: (1) never select
    an arm whose estimated effect for this cluster is negative (no-harm floor); (2) apply the wellbeing penalty as a
    constraint so over-target sessions down-rank engagement-heavy arms; (3) only sample experimental arms permitted by
    le-experimentation-guardrails (consent + approved review register). pgTAP supabase/tests/causal_bandit_test.sql:
    an arm with negative CATE is never returned; over-target state changes the selection away from the engagement arm;
    with no consent/review row, no experimental arm is served (falls back to the best safe known arm).

- id: le-efficacy-ledger
  title: Auditable efficacy ledger with always-valid (sequential) inference
  material: yes
  model: opus
  depends: [le-cate-uplift]
  proof: `supabase test db` exits 0 (supabase/tests/efficacy_ledger_test.sql)
  prompt: |
    Migration supabase/migrations/0026_efficacy_ledger.sql: efficacy_ledger (id, claim text, cluster text, lever text,
    arm text, effect numeric, ci_low numeric, ci_high numeric, n int, method text, valid_through timestamptz, created_at)
    plus record_efficacy_claim() that computes an ALWAYS-VALID confidence sequence (anytime-valid bound, e.g. a
    confidence-sequence / e-process), so claims can be read anytime without p-hacking. Add evidence_export view
    (aggregate, no identifiers) for district/RFP use. pgTAP supabase/tests/efficacy_ledger_test.sql: the always-valid
    interval is wider than the naive z-interval for the same data and narrows monotonically as n grows on a fixture.

- id: le-offline-policy-eval
  title: Counterfactual offline policy evaluation as the pre-deploy safety gate
  material: yes
  model: opus
  depends: [le-causal-bandit, le-cate-uplift]
  proof: `deno test -A supabase/functions/policy-eval/index.test.ts` exits 0
  prompt: |
    Build supabase/functions/policy-eval/index.ts: estimate a candidate bandit policy's value from logged data using
    a doubly-robust estimator (IPS + the CATE model), BEFORE any child is exposed. Output estimated value + CI and a
    pass/fail vs the incumbent policy and vs a no-harm baseline. index.test.ts on a logged fixture: DR recovers a known
    policy's value within tolerance; a deliberately harmful candidate is flagged below the baseline (fail). This gate
    must be invoked by the deploy flow for any new policy (document the hook).

- id: le-experimentation-guardrails
  title: No-harm + consent + review-register enforcement for any child-facing experiment
  material: yes
  model: opus
  depends: [capture-live-migrations]
  proof: `supabase test db` exits 0 (supabase/tests/experimentation_guardrails_test.sql)
  prompt: |
    Children are the subjects; experimentation needs hard guardrails. Migration
    supabase/migrations/0027_experimentation_guardrails.sql:
    - experiment_review_register (id, arm_key, lever, hypothesis, reviewer_id, approved boolean, approved_at, notes).
    - Add 'adaptive_experimentation' as a consent feature; can_experiment(p_child, p_arm) DEFINER fn returns true only
      if there is an approved review-register row for the arm AND app_has_consent(p_child,'adaptive_experimentation')
      AND the arm has no negative estimated effect. Guard app_can_access_child.
    pgTAP supabase/tests/experimentation_guardrails_test.sql: can_experiment is false without an approved review row,
    false without consent, false for a negative-effect arm, and true only when all three hold. (Reviewer process +
    IRB-style sign-off policy doc = OPERATOR.)

# ---------- WORKSTREAM 4: ON-DEVICE / DISTILLATION ----------

- id: le-policy-distillation
  title: Distill the fleet policy into a compact on-device model
  material: yes
  model: opus
  depends: [le-cate-uplift]
  proof: `deno test -A supabase/functions/policy-distill/index.test.ts` exits 0
  prompt: |
    Build a pipeline (supabase/functions/policy-distill/, plus a model-export step using the repo's available ML
    toolchain — document which) that distills the fleet policy (strategy_registry CATE priors + bandit behavior)
    into a compact student model emitting the same per-context arm decision, exportable for on-device inference
    (e.g. a small tree/logreg or ONNX artifact). No raw child data in the artifact — train on cluster-level policy
    targets. Test: the distilled student reproduces the teacher policy's decisions on a holdout context set with
    >= 0.9 agreement; artifact contains no child identifiers. (Model hosting/keys = OPERATOR.)

- id: le-inference-cascade
  title: Uncertainty-gated cascade — on-device first, escalate only when unsure
  material: no
  model: sonnet
  depends: [le-policy-distillation]
  proof: `deno test -A supabase/functions/_shared/inference_cascade.test.ts` exits 0
  prompt: |
    Add supabase/functions/_shared/inference_cascade.ts: route(context) runs the distilled on-device policy and
    returns its decision when confidence >= tau, else escalates to a mid model, else to the frontier model. Expose a
    calibrated confidence and telemetry counters (local/mid/frontier rates). Pure/mocked tiers. Test: high-confidence
    contexts stay local (no escalation), low-confidence contexts escalate, and the local-handling rate on a mixed
    fixture exceeds a target (e.g. >= 0.9) — proving cost scales sublinearly. (Model keys/deploy = OPERATOR.)

- id: le-federated-update
  title: Federated on-device updates — gradients leave, raw child data does not
  material: yes
  model: opus
  depends: [le-policy-distillation]
  proof: `deno test -A supabase/functions/federated-aggregate/index.test.ts` exits 0
  prompt: |
    Build supabase/functions/federated-aggregate/index.ts: accept client model updates (gradients/weight deltas),
    aggregate them (FedAvg with basic robustness to outlier clients), and publish an improved global policy — without
    ever receiving raw interaction events. Document the on-device local-update contract. index.test.ts: aggregation
    combines simulated client updates and the aggregated model improves on a holdout vs the base; the input contract
    rejects/contains no raw per-item child events (only updates). Pairs with the existing "share strategies not data"
    swarm design. (Deploy/secrets = OPERATOR.)

OPERATOR:
  - Approve + apply each material migration to prod Supabase `santas-secret-workshop` (ref whhfugddqehxxbmwutsw) after merge.
  - Deploy edge functions (irt-calibrate, misconception-discover, prereq-causal, cate-uplift, policy-eval, policy-distill, federated-aggregate) and enable pg_cron + pg_net.
  - Provision secrets: embeddings/LLM API key (misconception-discover, skill placement, diagnostic distractors), ML training/host for distillation + ONNX runtime for on-device, model keys for the cascade tiers.
  - Stand up the IRB-style review process behind experiment_review_register; author the written no-harm / child-experimentation ethics policy; define `adaptive_experimentation` consent copy for parents.
  - Legal/compliance sign-off before any efficacy claim is published externally or any evidence_export is shared with a district/partner; confirm COPPA posture for on-device + federated data flows.
  - Wire le-offline-policy-eval as a required gate in the policy-deploy pipeline (no new bandit policy ships without a passing DR evaluation).
