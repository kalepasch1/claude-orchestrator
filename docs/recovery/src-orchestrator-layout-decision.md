# `src/orchestrator/` — decision: discard the layout, recover the tests

Decided 2026-09-10 by `recovered-src-orchestrator-layout-decision`, against
`origin/master` @ `bcacf428`. Evidence ref
`refs/orch-rescue/20260908T005236-claude-orchestrator-ca1fb88a`, read-only and
untouched.

**Option (b): port only the two test files onto the shipped `runner/` module,
dropping the `src/` layout.** With one correction to how the task framed it —
there was no porting to do.

## Why the decision is easier than it looked

The task presented this as a layout choice between two competing packages. It
is not, because the two recovered test files do not test `src/orchestrator/`:

```
runner/test_counterfactual_replay_unit.py:27        import counterfactual_replay as cfr
runner/test_counterfactual_replay_acceptance.py:28  import counterfactual_replay as cfr
```

Both import the module `origin/master` already ships. They were written against
`runner/counterfactual_replay.py`, they sit in `runner/`, and they run there
unmodified. So recovering them costs nothing in layout terms and commits the
repo to nothing.

That also removes the argument for option (a). Adopting `src/orchestrator/` and
migrating callers would restructure a repo whose every module lives in
`runner/`, in order to satisfy no consumer — not even the tests that arrived
with it.

Option (c), discard everything, would have thrown away 1537 lines of working
tests for a shipped module, and with them the defect below.

## What the recovered tests found

Against unmodified `master`: **115 passed, 1 failed.**

`TestPolicyDivergenceDetection::test_handles_malformed_decisions` asserts that
`has_policy_change({}, {"decision": "opus"})` is `False`. It returned `True`.

An empty prior decision has no route to have changed *from*, so the comparison
was `None` against `"opus"` — a policy divergence manufactured out of missing
data. That is the same false positive the function's own comment says it was
fixed for once already, arriving from the other side:

> otherwise new_route is always None and every replayed decision looks like a
> divergence

The fix returns `False` when the old output carries no route, because
unanswerable is not "changed". Narrow on purpose: a decision with a real prior
route still compares normally.

## Verification

`runner/counterfactual_replay.py` now passes both recovered suites **and** all
six pre-existing ones — 407 passed, 0 failed. The failure reproduces on
`master` without the fix, which is what makes it a defect report rather than an
opinion.

## Not recovered, deliberately

`src/orchestrator/__init__.py`, `orchestrator.py`, `policies/__init__.py`,
`runners/{__init__,counterfactual,replay_runner}.py`, plus
`runner/test_counterfactual.py` and `tests/runner/__init__.py`. Dropping a
second orchestrator package in alongside `runner/` would leave two competing
implementations of the same responsibility and no rule for which one callers
should use.

The evidence ref still holds all of it if this is ever revisited.
