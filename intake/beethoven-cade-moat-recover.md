PROJECT: beethoven

# The moat-machinery batch. HARD CONSTRAINT (verified 2026-07-13): `lancedb` is NOT importable
# and the runner has NO python dependency manifest — the convention is pure-stdlib +
# unittest.mock (see runner/tests/test_model_routing.py). EVERY module below must import + test
# with ONLY the standard library; any third-party import must be guarded `try/except ImportError`
# with a stdlib fallback. pytest is the merge gate.

- id: knowledge-store-stdlib
  title: Content-addressed knowledge store — stdlib-pure (LanceDB optional)
  material: no
  model: sonnet
  depends: []
  proof: `pytest runner/tests/test_knowledge_store.py -q` exits 0
  prompt: |
    `runner/knowledge_store.py`, ZERO hard third-party imports. API: `put(record)->hash_id`,
    `get(hash_id)`, `search(query,k,filters)` (keyword over the manifest + cosine over stored
    embedding vectors in pure python), `stats()`. Storage: content-addressed JSON under
    `corpus/experts/<bot>/` + `corpus/index/manifest.jsonl`. Injected `embedder` (default: cheap
    deterministic hashing embedder, no network). LanceDB ONLY as a guarded optional accelerator
    (`try: import lancedb except ImportError: pure-python index`). Test stdlib-only: put->get,
    content-hash dedupe, keyword+vector hit, filter by author/topic.

- id: cade-run-ledger-v2
  title: CADE run ledger — capture every run (the moat data)
  material: no
  model: sonnet
  depends: []
  proof: `pytest runner/tests/test_cade_run_ledger.py -q` exits 0
  prompt: |
    `runner/cade_run_ledger.py`: pure `record_run(run)->dict` capturing inputs (mandate, recipient,
    facts), weakness + alignment ledgers, determination + credential id, roster/bots used + their
    positions, and the later realized outcome (prevailed / RFIs raised / ruling). Versioned schema,
    deterministic, round-trip unit-tested. Stdlib only.

- id: legitimacy-gauntlet-v2
  title: Legitimacy Gauntlet — adversarial rounds + 0..1 confidence + receipt
  material: yes
  model: opus
  depends: []
  proof: `pytest runner/tests/test_legitimacy_gauntlet.py -q` exits 0
  prompt: |
    `runner/legitimacy_gauntlet.py`: `run_gauntlet(artifact,{verifiers})->GauntletResult` with
    sequential INJECTED verifiers: citation-verifier, source-authenticator, precedent-integrity,
    logic/entailment, adversary-league survival, peer cross-examination, independent reproduction.
    Aggregate to `confidence` in [0,1] (any unresolved citation/source/precedent failure hard-caps it
    low), per-round pass/fail, and an immutable `receipt` (rounds, challenges, verdicts, hash).
    Pure over injected verifiers; stdlib only. Test: clean artifact -> high confidence; hallucinated
    cite -> capped low + fail; missing reproduction -> lowered.

- id: gauntlet-gate-policy-v2
  title: Tiered entry gate — >=0.50 autonomous, <0.50 human-signoff wall
  material: yes
  model: sonnet
  depends: [legitimacy-gauntlet-v2]
  proof: `pytest runner/tests/test_gauntlet_gate.py -q` exits 0
  prompt: |
    `runner/gauntlet_gate.py`: `decide_entry(gauntletResult, thresholds?) ->
    {decision:'admit'|'human_review'|'reject', reason}`. Hard failure (unresolved citation/source/
    precedent) -> reject; confidence >= GAUNTLET_ADMIT_FLOOR (env, default 0.50) -> admit (no human);
    0 < confidence < floor -> human_review. Pure; unit-test the 0.49/0.50 boundary + hard-fail override.

- id: golden-engagements-v2
  title: Real end-to-end sample engagements — schema + public-source ingesters
  material: yes
  model: sonnet
  depends: [knowledge-store-stdlib]
  proof: `pytest runner/tests/test_golden_engagements.py -q` exits 0
  prompt: |
    `runner/golden_engagements.py`: schema for a real matter as an ordered stage sequence
    {stage_input, real_next_document, real_outcome} + ingester adapters (network INJECTED/mocked in
    tests; urllib only, no requests) for: Federal Register API (open), SEC EDGAR (open),
    regulations.gov (REGULATIONS_GOV_API_KEY), CourtListener/RECAP (COURTLISTENER_API_TOKEN) — both
    keys already exist in ~/Documents/apparently/.env. Ship the CONFIRMED real seed to
    `runner/seeds/golden_engagements_seed.json`:
      CFTC "Prediction Markets; Public Interest Determinations" — FR doc 2026-11854
      (91 FR 35806, NPRM 2026-06-12, 17 CFR Part 40, pp. 35806-35871), ANPRM 91 FR 12516
      (2026-03-16), related data-reporting NPRM 2026-13239 (2026-07-01); full text:
      https://www.federalregister.gov/documents/full_text/text/2026/06/12/2026-11854.txt
      statutory anchor: CEA 7 U.S.C. 7a-2(c)(5)(C); topics: event contracts, §40.11, "gaming".
      Plus source-specified: litigation (CourtListener: KalshiEX v. CFTC), contract (SEC EDGAR
      UPLOAD/CORRESP comment-letter arc), licensing (NV GCB / NJ DGE).
    Test with bundled fixtures, no live net.

- id: replay-harness-v2
  title: Stage-by-stage replay — run CADE at each stage, score vs the real outcome
  material: yes
  model: opus
  depends: [golden-engagements-v2, cade-run-ledger-v2]
  proof: `pytest runner/tests/test_replay_harness.py -q` exits 0
  prompt: |
    `runner/replay_harness.py`: `replay(engagement,{run_cade})->ReplayScore` — per stage, invoke an
    INJECTED `run_cade(stage_input)` with ONLY info available then, and score against the real next
    document + outcome (predicted-RFI recall vs the real comment/deficiency letter, argument overlap
    vs the winning brief, tenability vs prevailed). Write each stage to cade_run_ledger + the store.
    Stdlib; test on a fixture engagement. This is the objective backtest that trains everything.

- id: moat-loop-v2
  title: Moat loop + activation entrypoint (ingest -> replay -> capture -> index)
  material: yes
  model: sonnet
  depends: [replay-harness-v2, knowledge-store-stdlib]
  proof: `pytest runner/tests/test_moat_loop.py -q` exits 0
  prompt: |
    `runner/moat_loop.py` `run_moat_cycle({sources,run_cade})->summary` (ingest new stages, replay,
    capture, re-index, report backtest win-rate + calibration deltas) AND `runner/moat_activate.py`
    `trigger_once(seed_path=runner/seeds/golden_engagements_seed.json)` + a `--live` flag that hits
    the real OPEN endpoints (Federal Register/EDGAR need no key). Also `runner/ingest_fulltext.py`
    `ingest_fulltext(record_path, store, embedder)`: fetch `full_text_url` once (urllib), strip the
    HTML wrapper, chunk by section, embed each chunk into the store, save the raw blob to
    `corpus/blobs/<hash>.txt`, flip `full_text_status` to `ingested` — so no large blob ever passes
    through an agent context. Network injected/mocked in tests; stdlib only.

OPERATOR:
  - After merge: `python -m runner.moat_activate --live` starts real ingest+replay on the CFTC matter (keyless sources); keys for litigation/comments already in apparently/.env.
