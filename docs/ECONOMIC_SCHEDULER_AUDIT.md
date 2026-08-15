# Pricing / economic-scheduling owner module — audit

Findings for `backlog-batch-beethoven-7371e3f-implement-economic-slice-3-locate-audit-owner-mo`:
locate the owner module, document its interfaces and patterns, and say where new pricing
config belongs. Every claim below was re-measured against `origin/master` on 2026-08-12,
not carried over from a prior note.

## 1. Where the code lives

| Concern | Module | Notes |
| --- | --- | --- |
| Economic scheduling / revenue scoring | `runner/economic_scheduler.py` (346 lines) | **the owner module** |
| Revenue attribution inputs | `runner/revenue_attribution.py` | imported by the owner |
| Stripe-side revenue facts | `runner/stripe_revenue.py` | not imported by the owner |
| Canary economics | `runner/canary_economics.py` | separate lane |
| Tests | `runner/test_economic_scheduler.py` | **15 of 37 fail on master — see §4** |
| Prepared patch | `patches/economic-scheduler-revenue.patch` | **does not apply — see §5** |

`economic_scheduler.py` imports only `os, sys, json, math`, `db` and `revenue_attribution`.
It is stdlib + two first-party modules; there is no build step and no install to repair.

## 2. Public surface

```
load_ctx()                      -> ctx dict, every read fail-soft
predict_revenue(task, ctx)      -> _estimate: a tuple subclass
cost_benefit(task, ctx)         -> dict
score(task, ctx)                -> float
predict_revenue_bulk(tasks, ctx=None)
apply_routing(scored)
run()
```

`predict_revenue` returns `_estimate`, a **tuple subclass that also answers to field names**.
That is deliberate and is the single most important pattern to preserve: the implementation
and all four call sites unpack a 3-tuple, while 22 test assertions index
`result["point_estimate"]`. Commit `33a98b93` made both work rather than picking a winner.
New code should keep unpacking the tuple; new *tests* may use either form.

## 3. Patterns to follow

- **Config is env-var only, read at import.** `ORCH_ECONOMIC_SCHEDULER_ENABLED`,
  `ORCH_ROI_THRESHOLD`, `ORCH_REVENUE_CRITICAL_LANE_SIZE`,
  `ORCH_ECONOMIC_CONFIDENCE_BAND`. There is no config file and no `fleet_config` read in
  this module. New pricing config belongs here as another `ORCH_`-prefixed module-level
  constant with a literal default — that keeps it fleet-pushable via `fleet_control.py`
  (see CLAUDE.md) without adding a config-loading dependency to a module that currently
  has none.
- **Fail-soft everywhere.** `load_ctx` documents "every read is fail-soft", and
  `apply_routing` / `predict_revenue_bulk` skip a `None` row rather than raising
  (restored in `073419c8` after the contract had silently lapsed). Any new function must
  return a sensible default rather than propagate.
- **Two accepted spellings for context keys.** `ctx["kind_roi"]`/`ctx["error_rates"]` and
  `ctx["surface_returns"]`/`ctx["app_signals"]` are both read. Do not "clean this up" —
  the implementation and the tests each use one, and normalising to either breaks the
  other.
- **No mocking framework.** The tests build plain dicts via local `task()` / `ctx()`
  helpers and never patch `db`. New tests should do the same: `predict_revenue`,
  `cost_benefit` and `score` are pure given a ctx dict, so they need no seam.

## 4. The suite is 15/37 red on master, and that is a recorded decision — not rot

`python3 -m pytest runner/test_economic_scheduler.py` → **15 failed, 22 passed**.

Do not "fix" these blind. Commit `33a98b93` investigated them and left the remainder
deliberately, with the measurement written down: the two suites that existed then
**contradicted each other** — `test_economic_scheduler.py` requires a ±20% confidence band
(6 tests), the revenue suite required ±25% (2 tests); setting 0.25 fixed two and broke six.
The band was left at 20% behind `ORCH_ECONOMIC_CONFIDENCE_BAND` so the choice is a config
change, and `2d707a35` then deleted the contradicting suites.

**What is new since that decision, and is a genuine finding:**
`b5b24cb2` (2026-08-07) re-added `runner/test_economic_scheduler.py` after `2d707a35`
deleted it. The re-added file targets an API the module does not have:

| Failure | Count | Meaning |
| --- | --- | --- |
| `module 'economic_scheduler' has no attribute 'TOP_REVENUE_TASKS'` | 2 | the suite expects a constant master calls `REVENUE_CRITICAL_LANE_SIZE` |
| `float() argument must be … not 'dict'` | 2 | the suite passes `app_signals={"apparently": {"error_rate": 0.9}}`; master does `float(...get(project, 0))` on the nested dict |
| `could not convert string to float: 'oops'` | 1 | the suite feeds a non-numeric signal and expects fail-soft |
| assertion mismatches (bands, ordering, `inf`) | 10 | the arithmetic disagreements described in `33a98b93` |

So the re-added suite is not simply stale: at least three of its failures are the
**fail-soft contract being violated by real input shapes** (a nested dict and a
non-numeric value both raise out of `predict_revenue`). Those three are worth fixing on
their merits, independently of the band argument. The rest need the band decision made,
not more patches.

## 5. `patches/economic-scheduler-revenue.patch` no longer applies

`git apply --check` → `error: patch failed: runner/economic_scheduler.py:33`.

Its companion README states the check passed against origin/master, and that was true when
it was written. Master has since moved: the patch's context lines carry
`ORCH_ECONOMIC_ROI_THRESHOLD` and `TOP_REVENUE_TASKS`, master has `ORCH_ROI_THRESHOLD` and
`REVENUE_CRITICAL_LANE_SIZE`. The patch is refreshed in this change so it applies again;
its intent is unchanged.

**The bug the patch targets is still live.** Measured on master:

| Prompt | Boosted by |
| --- | --- |
| `fix stripe payment crash on checkout` | `payment`, `stripe` |
| `add payment integration for marketplace` | `payment`, `marketplace` |
| `refactor pricing page copy` | `pricing` |

The first is a stability task and the third is copy work; both take the 1.5x revenue boost
on an incidental mention.

**Do not apply the patch without resolving this conflict first.**
`test_economic_scheduler.py:76` asserts that `"fix the stripe billing flow"` **must** be
boosted 1.5x — the live suite encodes the exact behaviour the patch calls a bug. The patch
survives that specific test only because it keeps `billing` as a keyword; the disagreement
about intent is unresolved either way. That is a product decision (does "fix X payment bug"
count as revenue work?), and it belongs to the apply-slice with an owner, not to a silent
rebase.

## 6. Recommendation

1. New pricing config → a module-level `ORCH_`-prefixed constant in
   `runner/economic_scheduler.py`, literal default, no new imports.
2. Preserve the `_estimate` tuple-subclass return and the dual context-key spellings.
3. Fix the three fail-soft violations in §4 (nested-dict and non-numeric signals) as their
   own change — they are contract bugs, not band disagreements.
4. Settle the "does a payment *bugfix* count as revenue work" question before applying the
   §5 patch, and record the answer next to `ORCH_ECONOMIC_CONFIDENCE_BAND` so the next
   audit does not have to rediscover it.
