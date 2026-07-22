PROJECT: beethoven

- id: backlog-blitz-batch-fusion-unpause
  title: Un-pause batch_fusion and fuse remaining small same-repo mechanical tasks
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m unittest discover -s runner/tests -p "test_batch*.py"` exits 0
  prompt: |
    Check current repo state first: batch_fusion.py has been repeatedly created/removed by
    concurrent fleet agents during the 2026-07-08 backlog-blitz session — if it already exists
    and is unpaused, verify it's actually running (check runner.log for `[sched] batch_fusion.py`
    ticks and check controls/fleet_config for anything gating it) and skip to the fusion-quality
    check below. If it doesn't exist or is gated off, un-pause/build it.

    Goal: fuse remaining small same-repo mechanical QUEUED tasks (docs, lint, mechanical
    refactors, config bumps) into batches of 5-10 tasks per coding session, same project, same
    lane, to cut per-task overhead. Respect existing dedup/fingerprint logic (don't re-fuse
    tasks already batched). Fail-soft: if fusion logic errors, fall back to unfused single-task
    claiming rather than wedging the runner.

    20+ test cases: batch size bounds, cross-project isolation (never fuse across projects),
    priority ordering preserved, partial-batch failure handling (one task in the batch fails —
    others still land), idempotency of re-running the fuser.

- id: backlog-blitz-drain-mode-and-ratio-cap
  title: Add drain_mode config + ORCH_META_PRODUCT_RATIO_CAP enforcement at task insert
  material: no
  model: sonnet
  depends: []
  proof: `python3 -m unittest discover -s runner/tests -p "test_drain*.py" "test_*ratio*.py"` exits 0 (adjust pattern to actual test filenames)
  prompt: |
    Note: as of 2026-07-08 there is no existing `drain_mode` concept anywhere in this codebase
    (grepped runner/*.py — zero hits). Don't assume it exists; design it fresh, fail-soft
    default OFF (i.e. generators run normally unless a config row explicitly sets drain mode).

    1. Add a `fleet_config` key `ORCH_DRAIN_MODE` (bool, default false) and a per-generator-name
       drain list `ORCH_DRAIN_GENERATORS` (default: colosseum, cade_tournaments, agent_market,
       committees, bot_factory, business_radar — check actual module names in runner/ first,
       some of these speculative-generator modules may have been renamed or removed since this
       mission was written; only reference modules that actually exist).
    2. When ORCH_DRAIN_MODE is true, any periodic job whose module name is in
       ORCH_DRAIN_GENERATORS should skip task generation (but keep running its other duties,
       e.g. cleanup) — fail-soft: unknown module name in the drain list is a no-op, not an error.
    3. Add `ORCH_META_PRODUCT_RATIO_CAP` (default 0.5) enforced at task insert time: track the
       ratio of meta-work tasks (kind in recovery/release-fix/improve) vs product-work tasks
       inserted in a rolling 24h window; if a new meta-work task insert would push the ratio
       above the cap, either queue it at lowest priority or reject with a clear reason logged
       on the task row (your choice — document which, and why, in the module docstring).
    4. This is a config/insert-path change, not schema/deploy/security — no material approval
       needed per repo guardrails, but still write a scoped commit, not a monolith.

    20+ tests: ratio cap math at boundary (exactly at cap, just over, just under), drain list
    matching (exact match, unknown name, case sensitivity), default-off behavior (no config row
    present → nothing changes), concurrent insert race (two tasks inserted near-simultaneously
    shouldn't both slip past the cap check if that matters for your chosen enforcement point).
