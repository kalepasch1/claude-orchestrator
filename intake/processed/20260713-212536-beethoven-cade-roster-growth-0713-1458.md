PROJECT: beethoven

# CADE roster completion + the CONTINUOUS-SCHOLARSHIP growth loop (bots that keep
# growing their expertise, not point-in-time). Builds on the shipped `runner/bot_factory.py`
# (BotSpec / run_eval / build_bot(spec, invoker) -> {manifest, admission}; floors
# CALIBRATION_FLOOR=0.6, PASS_RATE_FLOOR=0.7, MIN_EVAL=5) and runner/bots/*.py.
# SAFETY POSTURE (enforced in every task): a bot's self-generated theory/treatise or any
# newly-gathered source is STAGED as 'candidate' knowledge and only enters live use after it
# passes the factory eval/calibration gate AND (material) human SME sign-off. Autonomous
# browsing is default-OFF, sandboxed, injected in tests. pytest is the merge gate.

- id: bot-adversarial-regulator-fix
  title: Land the missing adversarial-regulator bot (diagnose why it gated/failed)
  material: no
  model: sonnet
  depends: []
  proof: `pytest runner/tests/test_bot_adversarial_regulator.py -q` exits 0
  prompt: |
    The 5th first-wave bot never landed (runner/bots/ has cftc/citation/de_chancery/state_gaming
    but NOT adversarial_regulator). First DIAGNOSE: build the spec and run it through
    `bot_factory.build_bot` with a faithful mock invoker and print the eval report — the likely
    cause is a golden `eval_set` whose `expected` stances the mock can't hit, or <MIN_EVAL items,
    or calibration below floor. Then add `runner/bots/adversarial_regulator.py` (role='adversary',
    corpus_filter over enforcement actions + C&Ds + deficiency notices, priors_tag=
    'skeptical_regulator', >=5 well-formed eval items scored on ANTICIPATING real objections/RFIs)
    and `runner/tests/test_bot_adversarial_regulator.py` that builds + admits it with a faithful
    mock invoker. This bot is the league's core adversary.

- id: bot-spec-autogen
  title: Spec-from-corpus autogeneration — the factory proposes the roster
  material: no
  model: sonnet
  depends: [bot-adversarial-regulator-fix]
  proof: `pytest runner/tests/test_bot_spec_autogen.py -q` exits 0
  prompt: |
    Add `runner/bot_spec_autogen.py`: `propose_specs(corpus_stats, matter_volume)` that takes
    corpus cluster stats (issuer/authority/topic counts) + matter-volume weights and emits ranked
    candidate `BotSpec`s (corpus_filter + priors_tag + a draft eval_set skeleton), so the roster
    is DESIGNED from the corpus instead of hand-authored. Pure; inputs passed in (no live corpus in
    the test). Add `runner/tests/test_bot_spec_autogen.py`: dense clusters yield specs, ranking by
    volume, dedupe vs existing runner/bots. Do NOT auto-admit — proposals still go through
    build_bot's gate + human review. This is the roster multiplier.

- id: bot-recert-loop
  title: Continuous bot re-certification (bots decay as law changes)
  material: no
  model: sonnet
  depends: [bot-adversarial-regulator-fix]
  proof: `pytest runner/tests/test_bot_recert.py -q` exits 0
  prompt: |
    Add `runner/bot_recert.py`: `recertify(bot_manifests, invoker) -> [{id, admission, delta}]`
    that re-runs each bot's eval via `bot_factory.run_eval` and flags demotion when calibration or
    pass-rate drops below floor (reuse the factory floors). Pure over injected invoker. Add
    `runner/tests/test_bot_recert.py`: a bot that now fails is demoted; a stable one holds. Do NOT
    wire into the live scheduler here (separate human-approved step). Generalizes the frontier
    outcome→reliability calibration from oracle sources to the expert bots.

- id: bot-roster-court
  title: Roster-as-a-court — convene admitted bots into a panel determination
  material: yes
  model: opus
  depends: [bot-adversarial-regulator-fix]
  proof: `pytest runner/tests/test_roster_court.py -q` exits 0
  prompt: |
    Add `runner/roster_court.py`: `convene(issue, admitted_manifests, invoker) -> Determination`
    that invokes authority/discipline/adversary/reviewer/recipient bots as a PANEL, aggregates
    their PersonaPositions into a calibrated determination WITH a dissent record, and shapes the
    output for the CADE determination-credential kernel (@darwin/kernel/cade credential — the
    determination that federation/finality/RaaS consume). Pure orchestration over injected invoker
    (deterministic test). Add `runner/tests/test_roster_court.py`: unanimous → high confidence;
    split → dissent recorded + lower confidence; empty roster handled. This bridges the bot factory
    to the credential kernel — the roster becomes a verifiable tribunal. CANDIDATE-SHARED.

- id: bot-knowledge-aggregator
  title: Knowledge aggregation — build a bot's profile from its sources/publications
  material: no
  model: sonnet
  depends: [bot-adversarial-regulator-fix]
  proof: `pytest runner/tests/test_bot_knowledge_aggregator.py -q` exits 0
  prompt: |
    Add `runner/bot_knowledge.py`: `aggregate_profile(bot_id, sources) -> ProfileDelta` that folds
    a bot's sourced publications/authorities (passed in as records: {title, issuer, date, text,
    provenance}) into an updated profile — extracted house doctrine, key authorities, positions
    held, and a freshness map — WITHOUT calling the network in the test. Emits a ProfileDelta that
    `bot_factory` can fold into the manifest (additive; never drops the seeded base). Add
    `runner/tests/test_bot_knowledge_aggregator.py`. This is the "build out their profiles" step;
    live source ingestion is an OPERATOR data-gathering step.

- id: bot-research-loop-scaffold
  title: Autonomous continuous-scholarship loop (SANDBOXED, default-off spike)
  material: yes
  model: opus
  depends: [bot-knowledge-aggregator, bot-recert-loop]
  proof: `pytest runner/tests/test_bot_research_loop.py -q` exits 0
  prompt: |
    Add `runner/bot_research_loop.py`: `research_cycle(bot, { browser, invoker, adversary })` that,
    for one bot, (1) gathers new domain sources via an INJECTED `browser` (claude-chrome adapter in
    prod; mock in tests), (2) forms/updates a candidate theory/treatise via `invoker`, (3) STRESS-
    TESTS it against the adversary league + the bot's eval_set, (4) stages the result as
    `candidate` knowledge with its test score — it NEVER auto-enters the live corpus. Gated by a
    default-OFF flag `CADE_BOT_RESEARCH_ENABLED`. Pure/injected test:
    `runner/tests/test_bot_research_loop.py` covers the staging + that a theory failing the
    adversary is NOT promoted + that the flag defaults off (no-op). This makes bots GROW their
    expertise continuously, safely. Enabling real autonomous browsing + a browse budget = OPERATOR.

- id: bot-collaboration
  title: Multi-bot collaboration — co-author / adversarially debate a treatise
  material: no
  model: sonnet
  depends: [bot-research-loop-scaffold]
  proof: `pytest runner/tests/test_bot_collaboration.py -q` exits 0
  prompt: |
    Add `runner/bot_collaboration.py`: `coauthor(topic, bots, { invoker }) -> {draft, dissent,
    testScore}` where multiple bots (e.g. an authority bot + an adversary bot + a reviewer bot)
    iteratively draft and critique a treatise/theory until convergence or a round cap, producing a
    draft with a dissent record and a test score. Pure orchestration over injected invoker
    (deterministic). Add `runner/tests/test_bot_collaboration.py`. Output is staged 'candidate' like
    the research loop — promotion needs the eval gate + SME review.

- id: cade-run-ledger
  title: CADE-run capture schema + writer (the proprietary moat data)
  material: yes
  model: sonnet
  depends: []
  proof: `pytest runner/tests/test_cade_run_ledger.py -q` exits 0
  prompt: |
    Add `runner/cade_run_ledger.py`: a pure serializer `record_run(run) -> dict` capturing EVERY
    real CADE run's moat signal — inputs (mandate, recipient, facts), the weakness + alignment
    ledgers, the determination + credential id, the roster/bots used + their positions, and the
    LATER realized outcome (prevailed / RFIs actually raised / ruling). Deterministic + versioned
    schema; unit-tested round-trip. This is the single most valuable thing to start gathering NOW —
    it trains the twin, calibrates thresholds, mines eval sets, and is the moat competitors can't
    copy. Live persistence target (Supabase table) + wiring each app to emit = OPERATOR.

OPERATOR:
  - Data gathering (start NOW — highest ROI, low risk): persist cade_run_ledger records for every real CADE run across apparently/tomorrow/smarter (inputs → ledgers → determination → realized outcome), plus attorney overrides/edits and the ACTUAL RFIs/rulings each recipient issued.
  - Enable autonomous bot research (real claude-chrome browsing + budget) only after human sign-off; keep `CADE_BOT_RESEARCH_ENABLED` off until then. All self-generated theory stays 'candidate' until it passes the eval gate + SME review (unauthorized-practice / hallucinated-authority risk).
  - SME sign-off on each bot's golden eval_set and on any candidate treatise before it enters the live corpus.
