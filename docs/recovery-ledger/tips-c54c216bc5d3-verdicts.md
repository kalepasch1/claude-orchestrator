# Adjudication: 3 conflicted local branch tips (c54c216bc5d3 / d854da55ab98)

Base: `origin/master` @ 8a2e2e16. Every tip was treated as read-only — no branch
was deleted, force-updated, reset or moved. Per-file machine verdicts are in
`tip-hisanta.json`, `tip-autocreator.json`, `tip-testrouting.json`; the hand
review of everything the machine flagged DIVERGED is below.

Recovered in this commit: **2 files**. Everything else is master-newer,
identical, or deferred with a named reason.

## Tip 1 — `agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2-clean-129448` (358297fa)

| verdict | count | files |
|---|---|---|
| SUPERSEDED_BY_NEWER | 4 | `hisanta/__init__.py`, `hisanta/contracts/family.py`, `hisanta/hisanta/contracts/family.py`, `hisanta/hisanta/mastery/engine.py` |
| IDENTICAL | 1 | `hisanta/tests/test_contract_singleton.py` |
| DIVERGED | 6 | the `runner/` files below |

**The `hisanta/hisanta/` nesting is not a packaging bug.** It was called out as
suspicious in the task. `hisanta/` is the project root inside the monorepo and
`hisanta/hisanta/` is the Python package inside it — the ordinary src layout.
`origin/master` carries the full nested tree (`gifting/`, `grandma/`,
`kindness/`, `mastery/`, `school/`), and the tip is a pure-addition subset of
it. Nothing to fix and nothing to flatten.

**Nothing recovered.** All four hisanta files are `+22/-0`, `+183/-0`, `+49/-0`,
`+90/-0` in master's favour — master strictly extends the tip on every one, so
replaying any of them is a revert.

The 6 `runner/` files overlap follow-up `b7fb78ad`, which adjudicated the same
content from the `never-again-lane-daemon` snapshot and reached the same
conclusion: master added the `lane_guard` single-instance lock to
`benchmark_redlines` / `expert_corps` / `foulkon_sync` *after* this tip, in
response to the legal_docket 14-concurrent-copies incident that stalled the
fleet. The tip predates the lock and would remove it. `slo_controller.py` and
`test_slo_controller.py` are load-bearing and master-newer. **Nothing taken from
this tip's runner/ side**, which is also what keeps the two follow-ups from
producing conflicting recoveries.

## Tip 2 — `agent/improve-missing-branch-auto-creator-slice-3-...-clean-152441` (dc65c542)

| verdict | file | snapshot -> master |
|---|---|---|
| IDENTICAL | `CLAUDE.md` | — |
| DIVERGED | `runner/periodic.py` | +201 / -5 |
| DIVERGED | `runner/repo_setup_repair.py` | +106 / -3 |
| DIVERGED | `runner/runner.py` | +380 / -23 |

**Nothing recovered.** Every file is overwhelmingly master-newer. `runner.py` is
load-bearing for the fleet and is +380/-23 in master's favour; taking any side
of it wholesale is exactly the failure mode this task exists to avoid. The small
tip-side deltas are within regions master rewrote wholesale, so there is no hunk
that is both absent from master and still correct against master's shape.

## Tip 3 — `agent/improve-value-aware-test-routing-early-exit-r-slice-3-fix-broken-tests-clean-151469` (a9e98fc3)

| verdict | file | snapshot -> master | outcome |
|---|---|---|---|
| DIVERGED (in fact absent on base) | `tests/runner_modules.py` | +0 / -67 | **RECOVERED** |
| DIVERGED | `tools/convention_lint.py` | +340 / -62 | **one hunk PORTED FORWARD** |
| DIVERGED | `tests/test_db_connectivity.py` | +73 / -112 | DEFERRED, reason below |

### `tests/runner_modules.py` — recovered whole

Does not exist on `origin/master` at all; the classifier reported DIVERGED only
because it measured diff direction before checking base presence (a real gap in
`adjudicate_evidence_snapshot.py`, noted here for the next pass). `+0/-67` means
master contributes nothing and the tip contributes 67 lines.

It fixes a genuine ordering bug: `runner/` is both a package and the directory
holding `runner.py`, so `import runner` binds to whichever wins the `sys.path`
race, and `sys.modules` freezes that choice for the whole session. `load()`
imports by explicit file location; `load_isolated()` returns a private copy so
transport tests cannot leak a placeholder endpoint into later tests. Pure
addition — nothing on master imports it yet — so recovering it cannot regress
anything. Verified: `load("db")` resolves to `runner/db.py`, `load_isolated`
returns a distinct object and leaves `sys.modules["db"]` untouched, and a
missing module raises `ImportError` rather than returning a broken object.

### `tools/convention_lint.py` — one hunk ported forward, not replayed

Master is +340 lines over the tip (`_check_scan_window`, the rule registry, the
`_record`/ratchet plumbing). Replaying the tip would delete all of it. Exactly
one thing in the tip is absent from master and still correct: the silent-handler
rule is broadened from *bare* `except: pass` to *any* handler whose body is only
`pass`, with docstring-only bodies counted as silent.

That is the rule CLAUDE.md actually states — "A silent `except Exception: pass`
is the defect; a logged one is the convention" — and master's bare-only check
misses every typed silent handler. Ported onto master's shape: the tip's
`_handler_is_silent` predicate, called from master's newer `_record` path rather
than the tip's `self.violations.append`.

Verified: a `except Exception: pass` in a public function now fires
`FAIL_SOFT_ERROR`, and `pytest -k convention` is unchanged at **15 failed / 154
passed / 8 skipped**, identical to the same run on clean `origin/master`.

### `tests/test_db_connectivity.py` — deferred, with the reason

Master is +73 lines over the tip and still uses bare `import db`, which is the
very ordering bug `runner_modules.py` exists to fix. Porting the tip's isolated
`db_module` fixture forward is the right follow-up, but it is a behavioural
change to a file whose failure count must not move, and it only becomes possible
once `runner_modules.py` is on master. Deferred deliberately rather than
half-applied. Baseline confirmed unchanged at 6 failed / 1 passed, identical to
clean `origin/master`.
