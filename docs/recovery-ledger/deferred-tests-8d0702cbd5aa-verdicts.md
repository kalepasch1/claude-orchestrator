# Deferred tests needing newer module versions — verdicts

Base: `origin/master` @ 8a2e2e16. Every one of the seven deferred items has an
explicit verdict below. No rescue ref was deleted, reset or moved.

**Landed green: 3 of 7. Already resolved on master: 2. Deferred with a named
reason: 2.**

| # | test file | on master? | verdict |
|---|---|---|---|
| 1 | `runner/tests/test_bandit_performance_tracker.py` | absent | **RESTORED + subject ported forward — 46/46 green** |
| 2 | `runner/tests/test_priority_queue_roi.py` | absent | **RESTORED + subject ported forward — 18/18 green** |
| 3 | `hisanta/tests/test_contract_singleton.py` (addendum) | present, ERRORING | **UNBLOCKED — 18/18 green** |
| 4 | `scripts/reconcile-evidence.test.mjs` | present | already resolved — 35/35 green, `buildPreservationPlan` is on master |
| 5 | `runner/tests/test_20260816_card_loop_and_stderr.py` | present, red | DEFERRED — see below |
| 6 | `runner/tests/test_20260817_prepare_toolchain.py` | present, red | DEFERRED — see below |
| 7 | `runner/tests/test_20260816_branch_share_fetch.py` | present, red | DEFERRED — see below |

## 1. `bandit.PerformanceTracker` / `bandit._z_for` — ported forward

The test file (blob `ff7bde48`) fully specifies both symbols, so this was ported
forward onto master's `bandit.py` rather than the rescue-ref version of the
module being replayed over it. `BanditSelector`, `choose`, `_reward`, `_outcomes`
and `MODELS`/`EPSILON` are untouched; the file's own
`BackwardCompatibilityTest` asserts that surface is preserved and passes.

What was added:

- `PerformanceTracker` — per-arm reward samples that keep the *tracking*
  question ("which arm has the higher mean") strictly separate from the
  *acceptance* question ("is that difference established"). Conflating them is
  how three lucky samples become a routing decision. An unobserved arm returns
  `None`, never `0.0`: zero is a claim about performance, `None` says "never
  ran".
- `_z_for` — two-sided z multiplier, fail-soft to 95% on `None`, a string, or
  anything outside (0, 1). Backed by a table of the conventional published
  values, because 95% must read as 1.96 and not 1.9599639845 when a human
  compares a log line against a textbook; levels off the table fall through to
  the exact inverse normal CDF.
- `tracker_from_outcomes` — builds a tracker from the same rows `choose()`
  filters, including the "missing `kind` means build" rule, so the gate and UCB1
  can never disagree about which rows they saw.
- The gate itself in `choose()`, after the cold-start check and **before** the
  epsilon draw. If one arm is established as better than *every* rival,
  exploring is no longer buying information, it is buying a worse model at
  random. `BANDIT_ACCEPTANCE=false` plus a module reload restores the pre-gate
  behaviour exactly, which the test file verifies by showing exploration goes
  back to picking both arms.

`accepted_leader` requires beating every rival, not just the runner-up: a leader
that is only ahead of second place while third is still within reach is a coin
flip with extra steps.

## 2. ROI pinning in `priority_queue.py` — ported forward

The test file (blob `06c5432f`) specifies `ORCH_PINNED_MIN_ROI`. Ported onto
master's module; prefix pinning is unchanged and its three existing tests pass.

The load-bearing decisions, all of which the tests pin down:

- **An unparseable threshold disables value pinning; it does not default to
  0.0.** A zero threshold pins every task, so a typo in `fleet_config` would
  silently move the entire queue into the express lane — which is not a degraded
  mode, it is the express lane ceasing to mean anything. The parse failure is
  written to stderr rather than swallowed, per the repo's fail-soft convention.
- **Prefix wins over ROI when both apply.** A named prefix is an explicit
  operator decision about a class of work; an ROI score is a measurement.
  Attributing the pin to the measurement would hide that someone asked for the
  lane by name. `pin_reason` carries which one fired, and `stats()` counts them
  separately.
- **`bool` is not a number.** `bool` subclasses `int`, so `roi: True` would
  otherwise read as 1.0 and a flag field would silently become a value score.
- **The first score field present decides, even if it fails to parse.** Falling
  through from an unusable `roi` to `ev_score` would let a malformed value
  promote a task on a weaker signal.

## 3. `hisanta` — the real find

The addendum asked to restore `hisanta/tests/test_contract_singleton.py`, which
"needs a newer `hisanta/contracts/family.py` exposing `CANONICAL_PATH` and
`CANONICAL_MODULE`". The test file and both symbols were already on master. The
reason it could not run is worse than a missing symbol:

**Four files on `origin/master` carry committed merge conflict markers**, so the
entire `hisanta` package fails to import and all five hisanta test modules error
at collection:

- `hisanta/__init__.py` (1 block)
- `hisanta/contracts/family.py` (3 blocks)
- `hisanta/hisanta/contracts/family.py` (2 blocks)
- `hisanta/hisanta/mastery/engine.py` (1 block)

All seven blocks resolved newest-implementation-wins, taking the incoming
`agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2` side. That is
also the side `test_contract_singleton.py` requires: the nested
`hisanta/hisanta/contracts/family.py` holds the definitions and the top-level
`hisanta/contracts/family.py` is a load-by-path re-export shim, so both spellings
of the module are the *same objects* and a cross-path `isinstance` or enum
comparison cannot fail. `hisanta/__init__.py` keeps the HEAD side's explicit
`__path__` rebinding from `globals()` (a bare `__path__.append` trips the
pyflakes undefined-name guard) with the clearer explanation from the other side
merged into its docstring.

Result: **5 collection errors / 0 tests run → 95 passed, 5 skipped.**

This also settles the question raised in follow-up `c54c216bc5d3` about whether
`hisanta/hisanta/` is a packaging bug. It is not — it is the ordinary src
layout, and `__init__.py` extends `__path__` over it deliberately, appending
rather than prepending so the nested copy can never shadow `hisanta.contracts`.

### The 5 skips

`hisanta/tests/test_family_contract_single_source.py` asserts the **inverted**
arrangement: nested-is-shim, top-level-is-canonical. It and
`test_contract_singleton.py` are the two sides of the same conflict and cannot
both hold. Because every one of these files carried conflict markers, *neither*
guard had run and the contradiction went unnoticed.

Marked `pytest.mark.skip` with the reason rather than deleted, so the argument
stays in the tree. The live guard against the duplicate growing back is
`test_contract_singleton.py`, which covers the same failure in the direction that
actually landed.

## 5–7. Deferred, with the reason

These three files are already on master and already red — 22 failures between
them. They are **not** blocked on restoring a test or porting a symbol. They
demand behavioural changes across `runner/runner.py`, `merge_train.py` and
`release_train.py`:

- `merge_train._retire_card` and `_recently_finalised`, plus routing all 13
  terminal `decided_by` stamps in `runner.py` through the retirement path
- removing tail-truncation at 18 sites across `runner.py`, `release_train.py`,
  `merge_truth.py`, `branch_durability.py`, `merge_train.py`
- `release_train.PREPARE_TIMEOUT_S`, `_local_bin`, `_prepare_cmd`, and replacing
  bare `npx` (which downloads and times out)
- a fetch before the branch-share push, and paging the scan to exhaustion

That is four independent features on the fleet's most load-bearing files. Doing
them in the same commit as a `bandit`/`priority_queue`/`hisanta` recovery would
produce a diff nobody can review and put the merge train at risk on the one path
that must not break. Deferred deliberately, as four separate follow-ups, with
the failing symbols named above so none of them starts from zero.

`runner/tests` is unchanged against clean `origin/master` apart from the new
passes — no regression.
