# Build/Test Verification — convention conformance lints

Slice: `backlog-batch-beethoven-22ee5bc-recover-convention-conformance-lints-verify-buil`
Base: `master` @ `64a7b0ef`

## Commands run

| Command | Result |
| --- | --- |
| `python3 -m compileall -q runner` | exit 0 — no syntax regressions |
| `python3 tools/convention_lint.py --json` | runs clean, emits valid JSON |
| `python3 -m pytest tests/test_convention_lint.py tests/test_convention_conformance.py tests/test_lint_conventions.py tests/test_lint_conventions_comprehensive.py tests/test_convention_rule_gen.py -q` | 170 passed (before change) / 175 passed (after change, incl. 5 new) |

## Issue found and fixed

`ConventionChecker._check_fail_soft_error_handling` used `ast.walk(node)`, which crosses
function scope boundaries. Two consequences:

1. A `raise` inside a **nested** helper was reported against its enclosing public
   function. Concrete case: `runner/dependency_release.py::build_release_graph` was
   flagged because its inner `dfs()` raises `CyclicDependencyError`. The rule as
   documented in `CONVENTION_LINT.md` applies to *public module-level* functions only.
2. Nested functions were themselves visited and reported as public functions
   (`dfs` at `dependency_release.py:146`), even though they are not part of any
   module's public surface.
3. Symmetrically, a `try/except` in a nested helper was credited as the *enclosing*
   function's fail-soft handler, suppressing real violations.

**Fix:** added `ConventionChecker._own_nodes()`, which walks a function body without
descending into nested `FunctionDef`/`AsyncFunctionDef`/`ClassDef` nodes, and an
explicit `len(self.function_context) > 1` guard so nested definitions are skipped.
Both the raise check and the bare-`except: pass` check now use `_own_nodes`.

**Effect on the lint baseline:** 74 → 68 violations
(`FAIL_SOFT_ERROR` 65 → 59; `HARDCODED_SECRET` 9 unchanged). All six removed entries
were nested-scope false positives; no true positive was suppressed.

Regression coverage added in `tests/test_convention_lint_nested_scope.py` (5 tests),
including a case asserting that a nested handler does **not** excuse an enclosing
`raise`, so the fix cannot regress into over-suppression.

## Pre-existing issues (NOT introduced by this change, NOT fixed here)

`python3 -m pytest tests/` interrupts with 12 collection errors, all the same root
cause and all present on unmodified `master`:

```
ModuleNotFoundError: No module named 'runner.<mod>'; 'runner' is not a package
ImportError: cannot import name 'prompt_evolver' from 'runner' (runner/runner.py)
```

`runner/` has no `__init__.py`, so `import runner` resolves to the module
`runner/runner.py` rather than the package directory. Affected files:
`test_assumptions_ledger`, `test_commit_containment`, `test_decompose_idempotency`,
`test_differential_gate`, `test_enqueue`, `test_evidence_gate_check`,
`test_prompt_evolution_bandit`, `test_prompt_evolver_exploration`,
`test_reaudit_merged`, `test_scope_gate`, `test_self_audit_rerun`, `test_vacuity_gate`.

This is out of scope for this slice (it would change import resolution repo-wide) and
is recorded here so the next toolchain-repair slice can pick it up. The convention-lint
suites do not import `runner` and are unaffected.
