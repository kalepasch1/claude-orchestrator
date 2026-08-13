# Owner-module audit — pricing / configuration / economic scheduling

Slice: `backlog-batch-beethoven-7371e3f-implement-economic-slice-3-locate-audit-owner-mo`
Base: `master` @ `64a7b0ef`

Audit of where pricing/config code already lives, what patterns it uses, and where new
pricing-config code belongs. Findings only — no behaviour changed by this slice.

## 1. Owner modules

Two distinct owners; conflating them is the mistake this audit exists to prevent.

| Concern | Owner | Lines | Status |
| --- | --- | --- | --- |
| **Pricing configuration** (tiers, rate limits, TTL) | `runner/pricing_config.py` | 151 | The owner. Purpose-built for this slice. |
| **Economic scheduling** (revenue prediction, ROI, routing) | `runner/economic_scheduler.py` | 346 | The consumer. |

Adjacent, and NOT the owner for this work:

| Module | Lines | Why it is not the target |
| --- | --- | --- |
| `runner/ploeh_s2s_pricing.py` | 254 | Fetches prices from an external cross-app service behind `PLOEH_S2S_SECRET`. Different axis: remote price *discovery*, not local config. |
| `runner/pricing_synthesizer.py` | 175 | Builds pricing inputs via the S2S bridge; falls back to a local mock (1000bp markup). Consumer of the above. |
| `runner/pricing_grid_reconstruction.py` | 251 | Grid reconstruction utility, already deduplicated into `PricingGridReconstructionUtil`. Unrelated to tier config. |
| `runner/canary_economics.py` | 88 | Promote/rollback on production cost+quality. Consumes `cost_slo`, not pricing tiers. |
| `runner/ev_scheduler.py` | — | The only in-tree importer of `economic_scheduler` (line 193). |
| `runner/marginal_value_scheduler.py`, `lane_scheduler.py`, `predictive_scheduler.py` | — | Sibling schedulers; none owns pricing. |

**`runner/pricing_config.py` is the sole reader of `ORCH_PRICING_*`** (verified by grep
across `runner/*.py`). New pricing-config code goes there, and nowhere else.

## 2. Current interfaces

```python
# runner/pricing_config.py
DEFAULT_TIERS       = {"free": 0.0, "pro": 199.0, "scale": 999.0}
DEFAULT_RATE_LIMITS = {"free": 100, "pro": 10000, "scale": 100000}
DEFAULT_TTL_SECONDS = 3600
ENV_TIERS, ENV_RATE_LIMITS, ENV_TTL     # "ORCH_PRICING_TIERS" / "_RATE_LIMITS" / "_TTL_SECONDS"
REQUIRED_KEYS = ("tiers", "rate_limits", "ttl_seconds")

class PricingConfigStore          # thread-safe holder; callers do NOT touch it
load_pricing_config(refresh=True) # -> {"tiers", "rate_limits", "ttl_seconds"}; never raises
invalidate()                      # drop the cache so the next load re-reads the env
```

```python
# runner/economic_scheduler.py
ENABLED, ROI_THRESHOLD, REVENUE_CRITICAL_LANE_SIZE, REVENUE_KEYWORDS  # import-time env reads
load_ctx()                        # the initialization path — builds ctx from db, fail-soft
predict_revenue(task, ctx)        # -> _estimate(point, low, high)
cost_benefit(task, ctx)           # -> {"predicted_revenue","estimated_cost","roi","worthwhile"}
score(task, ctx)                  # deterministic combined score
apply_routing(scored) / run()     # daily job
```

## 3. Patterns to follow

**Config loading — a function, not a constant block.** `pricing_config` is explicit about
why (module docstring): `economic_scheduler` reads its three scalars off `os.environ` at
import time, which cannot be re-read after a fleet push and raises during import on a
malformed value. A *table* must not do that. Every call re-reads the environment;
`refresh=True` is the default so an `ORCH_`-pushed change lands on the next call rather
than the next restart, and `refresh=False` is the hot-loop path.

**Fail-soft, scoped per key.** `_json_map` falls back to the default for THAT key only, so
one malformed override cannot blank the table, and it prints a diagnostic before
swallowing — a silent fallback resurfaces later as mispriced work with no trace.
`_positive_int` rejects `<= 0`. `load_pricing_config` wraps the whole store call and still
returns every `REQUIRED_KEYS` entry, so a consumer can index the result unguarded.

**Deep copy on return.** `_isolate()` exists because `dict(config)` is shallow: a caller
doing `cfg["tiers"]["x"] = 1` would rewrite the shared table for every later reader, and
only on the `refresh=False` path — the hot path where it does the most damage.

**Env-var naming.** Every knob is `ORCH_`-prefixed so `fleet_control.py` can push it
fleet-wide. Follow this exactly; a non-`ORCH_` knob is not fleet-pushable.

**Module-level singleton + delegating module functions.** `_store = PricingConfigStore()`
with `load_pricing_config`/`invalidate` delegating. This is a repo convention and
`CONVENTION_LINT.md` Rule 3 enforces the shape — callers never thread an instance through.

## 4. Test patterns

Existing coverage: `tests/test_economic_scheduler.py` (7 tests, pure — no DB, no network),
plus `runner/test_economic_scheduler.py` and `runner/tests/test_ploeh_s2s_pricing.py`.

- `setUp` calls `pricing_config.invalidate()` and `self.addCleanup(pricing_config.invalidate)`
  — mandatory, or cached state leaks between tests.
- Env overrides via `mock.patch.dict(os.environ, {...})`; for the defaults case, `clear=False`
  plus an explicit `os.environ.pop(var, None)` per knob.
- The consumer is a `mock.Mock()` receiving the table, not a real scheduler.
- Mutation safety is pinned on the `refresh=False` path deliberately: with `refresh=True`
  every call rebuilds, so a shallow copy passes for the wrong reason.

**Caution when adding scheduler tests.** `runner/test_economic_scheduler.py` is red on
master (15 failed / 22 passed) and its own spec is self-contradictory — the confidence
band is asserted at ±20% in one file and ±25% in another, so no implementation can satisfy
both (documented in `economic_scheduler.predict_revenue`). Do not treat those failures as
a regression; diff the failure SET before and after any change.

## 5. Recommendations for preserving existing behaviour

1. **Put the config in `pricing_config.py`; put the *use* of it in the consumer.** The
   scoring functions should take the table off `ctx`, not import `pricing_config`
   themselves — that keeps them pure and mockable exactly as they are today.
2. **`load_ctx()` is the initialization path.** Load the table once there. Adding a key to
   `ctx` cannot change any existing score, which is what makes the wiring backward
   compatible by construction rather than by inspection.
3. **Make any new weighting inert under the defaults.** `DEFAULT_TIERS` is keyed by tier
   name (`free`/`pro`/`scale`), never by project name, so a project→price lookup returns
   0.0 for every project unless an operator pushes a project-keyed `ORCH_PRICING_TIERS`.
   A multiplier built on that is exactly 1.0 by default — live only when configured.
4. **Use `refresh=False` in `load_ctx()`.** It runs once per scheduling pass and callers
   may build several contexts in a loop; the cached table is the right read, and a fleet
   push still lands on the next process cycle.
5. **Prove compatibility by diffing the failure set**, not by counting passes: run
   `runner/test_economic_scheduler.py` before and after and assert the FAILED list is
   byte-identical. Given the pre-existing red suite, that is the only honest signal.
6. **Never divide by a free tier.** Normalise against the cheapest *paid* tier; `$0` is
   not a reference price, and a project on an explicit `$0` tier should be left unchanged
   rather than zeroed — the tier says nothing about the work's value.

## 6. Where the new code went

Implemented in sibling slice
`backlog-batch-beethoven-7371e3f-implement-economic-slice-3-integrate-pricing-wit`
(`agent/…-integrate-pricing-wit`, commit `079c1a02`), following every recommendation
above: `ctx["pricing"]` populated in `load_ctx()`, accessors `project_tier_price` /
`project_rate_limit` / `_tier_multiplier` added to `economic_scheduler.py`, weighting
applied in `predict_revenue`. Backward compatibility was verified the way §5.5 prescribes:
the `runner/test_economic_scheduler.py` failure set is byte-identical before and after
(15 failed / 22 passed), and 20 tests pass in `tests/test_economic_scheduler*.py`.
