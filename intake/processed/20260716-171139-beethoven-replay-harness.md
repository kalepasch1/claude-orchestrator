PROJECT: beethoven

# The one moat task that never landed. HARD CONSTRAINT (verified 2026-07-13): `lancedb` is NOT
# importable and the runner has NO python dependency manifest — the convention is pure-stdlib +
# unittest.mock (see runner/tests/test_model_routing.py). Any third-party import must be guarded
# `try/except ImportError` with a stdlib fallback. pytest is the merge gate.
#
# Context: legitimacy_gauntlet.py, gauntlet_gate.py, golden_engagements.py, moat_loop.py and
# runner/seeds/golden_engagements_seed.json are all now merged on master — build against them.

- id: replay-harness-v2
  title: Replay harness — re-run past engagements against the current CADE stack
  material: no
  model: sonnet
  depends: []
  proof: `pytest runner/tests/test_replay_harness.py -q` exits 0
  prompt: |
    `runner/replay_harness.py`, ZERO hard third-party imports (stdlib only; guard any optional
    accelerator with try/except ImportError + a pure-python fallback).

    Purpose: take a stored golden engagement (schema from `runner/golden_engagements.py`, seed at
    `runner/seeds/golden_engagements_seed.json`) and replay it through the current stack so we can
    measure whether CADE is getting better or worse over time. This is the regression spine of the
    moat: without it, model/prompt/gauntlet changes are unfalsifiable.

    API:
      - `replay(engagement, *, gauntlet=None, gate=None) -> ReplayResult`
        Re-runs one engagement. Injectable `gauntlet`/`gate` (default: the real
        `legitimacy_gauntlet` + `gauntlet_gate`) so tests never make network calls.
      - `replay_all(engagements, **kw) -> ReplayReport`
        Aggregate: pass/fail counts, mean gauntlet confidence, per-engagement deltas.
      - `compare(baseline_report, current_report) -> Delta`
        Regression detector: which engagements newly fail, which newly pass, confidence drift
        per engagement and in aggregate.
      - `ReplayResult` must record: engagement id, expected outcome, actual outcome, gauntlet
        confidence, gate admission decision, and whether it matched the recorded outcome.

    Determinism is non-negotiable: identical inputs must produce identical results. Seed any RNG
    (see `mulberry32` convention in the fleet's Monte-Carlo engines). No wall-clock in outputs.

    Tests (stdlib + unittest.mock only, no network):
      - replay of a known-good engagement reports matched=True
      - replay of an engagement whose recorded outcome disagrees reports matched=False
      - replay_all aggregates counts + mean confidence correctly
      - compare() detects a newly-failing engagement (the regression case that justifies the file)
      - compare() detects confidence drift below a threshold
      - determinism: two identical replays produce identical ReplayResults
      - a gauntlet that raises is captured as a failed replay, never propagates
