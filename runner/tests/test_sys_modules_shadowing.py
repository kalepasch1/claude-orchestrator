"""No NEW test module may replace a real runner module in sys.modules at import time.

pytest imports every test module during COLLECTION, before any fixture runs. So a
module-scope

    sys.modules["db"] = fake_db

is not scoped to that file. It rewrites `db` for every test that runs afterwards in the
same process, and unlike an environment variable there is no conftest restore that can
undo it -- the object is gone and the pollution is inside whatever snapshot anything
else took.

THIS IS NOT THEORETICAL. It is the single largest source of "green standalone, red in a
batch" in this suite, and 2026-08-25 spent most of a session on the consequences:

  * runner/tests/test_emit_task_log.py installed `sys.modules["db"] = fake_db` -- a
    SimpleNamespace with three lambdas -- and never restored it. Every later test got
    that in place of the database client. It was the cause of all 10 failures in
    test_done_to_merged_conversion.py and 10 more in test_eval_harness_causal.py, both
    of which went green the moment it was fixed, with no change of their own.

  * runner/test_account_pool.py hard-assigned SUPABASE_URL at module scope, repointing
    the control plane for the whole process (see test_env_import_side_effects.py, which
    freezes the environment half of this same problem).

  * runner/tests/test_branch_recovery_reproduce_missing.py patched one module attribute
    from three concurrent threads, which is not thread-safe and left a MagicMock bound
    permanently. Two tests in a different file failed with StopIteration because of it.

Each looked like a product regression. None was one.

This test does not try to drain the existing debt in one go -- it FREEZES it, exactly as
test_env_import_side_effects.py does for environment variables. The known sites are
listed below and MAY ONLY SHRINK. Anything new fails here, at the point it is
introduced, with an explanation instead of a multi-hour bisect.

To fix one:

    # before, at module scope                # after, scoped to the test
    sys.modules["db"] = fake_db              with patch.dict(sys.modules, {"db": fake_db}):
    import thing_under_test                      ...

or, where the module under test binds the fake at ITS import,
runner/env_during_import.import_with_env() gives it a private copy that cannot leak.
Then delete the entry from KNOWN_MODULE_SHADOWS.
"""
import ast
import os

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TESTS = os.path.join(_RUNNER, "tests")

#: (module path relative to runner/, shadowed module name) -- known, and may only shrink.
#: EMPTY, and it must stay that way.
#:
#: All 23 sites were drained on 2026-08-25. Four different shapes needed four
#: different fixes, which is why this was not one sweep:
#:
#:   * most were `sys.modules["db"] = stub` before an import -> wrapped in
#:     env_during_import.modules_during_import(), which restores what was there;
#:   * two files guarded with `if "db" not in sys.modules:`, which under pytest
#:     SKIPPED (conftest imports db first) so the module under test bound the real
#:     client, and standalone installed a stub that was never removed -- wrong in
#:     both directions, and the guard had to go, not just move;
#:   * two files needed import_with_stubs() instead, because something earlier in
#:     the run had already imported the module under test and a plain import was a
#:     no-op that handed back the copy bound to the real db;
#:   * three loaded runner.py as `sys.modules["runner"]`, replacing the PACKAGE --
#:     the very thing conftest's _runner_stays_a_package fixture exists to undo --
#:     and now load under a private name;
#:   * one file's stubs were referenced nowhere at all and were simply deleted.
KNOWN_MODULE_SHADOWS = set()


def _real_module_names():
    """Top-level modules that really exist in runner/."""
    return {name[:-3] for name in os.listdir(_RUNNER)
            if name.endswith(".py") and not name.startswith("test_")}


def _module_scope_shadows(path, real):
    """Names assigned into sys.modules at MODULE SCOPE that shadow a real module."""
    try:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
    except (SyntaxError, OSError):
        return []

    found = []
    for node in tree.body:                      # module scope only
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            for target in sub.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "modules"
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                        and target.slice.value in real):
                    found.append(target.slice.value)
    return found


def _current_shadows():
    real = _real_module_names()
    found = set()
    for directory in (_RUNNER, _TESTS):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            path = os.path.join(directory, name)
            rel = os.path.relpath(path, _RUNNER)
            for shadowed in _module_scope_shadows(path, real):
                found.add((rel, shadowed))
    return found


def test_no_new_module_scope_sys_modules_shadow():
    new = _current_shadows() - KNOWN_MODULE_SHADOWS
    assert not new, (
        "these test modules replace a REAL runner module in sys.modules at import time, "
        "which every test collected afterwards then receives:\n  "
        + "\n  ".join(f"{shadowed!r} in {module}" for module, shadowed in sorted(new))
        + "\n\nScope it with patch.dict(sys.modules, {...}) inside the test, or use "
          "env_during_import.import_with_env() if the module under test binds it at "
          "ITS import.")


def test_the_baseline_does_not_list_things_that_are_already_fixed():
    """A stale entry hides the next regression behind a fixed one."""
    stale = KNOWN_MODULE_SHADOWS - _current_shadows()
    assert not stale, (
        "these are in KNOWN_MODULE_SHADOWS but no longer present -- delete them:\n  "
        + "\n  ".join(f"{shadowed!r} in {module}" for module, shadowed in sorted(stale)))


def test_db_is_never_baselined_again():
    """`db` is the one that did the damage; the list may shrink but never grow.

    Kept as its own assertion so that adding a db shadow requires deliberately
    editing this number, not quietly appending one more line to a set of 23.
    """
    db_shadows = {entry for entry in _current_shadows() if entry[1] == "db"}
    baseline_db = {entry for entry in KNOWN_MODULE_SHADOWS if entry[1] == "db"}
    assert len(db_shadows) <= len(baseline_db), (
        "a new test module shadows `db` process-wide: "
        + ", ".join(sorted(m for m, _ in db_shadows - baseline_db)))


def test_the_detector_sees_a_planted_shadow(tmp_path):
    """Guards the guard -- an empty scan would make all of the above vacuously green."""
    planted = tmp_path / "test_planted.py"
    planted.write_text("import sys\nsys.modules['db'] = object()\n", encoding="utf-8")
    assert _module_scope_shadows(str(planted), {"db"}) == ["db"]


def test_the_detector_ignores_a_shadow_inside_a_function(tmp_path):
    """Only module scope leaks past collection; an in-test assignment is the FIX."""
    scoped = tmp_path / "test_scoped.py"
    scoped.write_text(
        "import sys\n\n\ndef test_x():\n    sys.modules['db'] = object()\n",
        encoding="utf-8")
    assert _module_scope_shadows(str(scoped), {"db"}) == []


def test_the_detector_ignores_a_name_that_is_not_a_real_module(tmp_path):
    """Installing a stub for something that does not exist shadows nothing."""
    stub = tmp_path / "test_stub.py"
    stub.write_text("import sys\nsys.modules['not_a_real_module'] = object()\n",
                    encoding="utf-8")
    assert _module_scope_shadows(str(stub), {"db"}) == []
