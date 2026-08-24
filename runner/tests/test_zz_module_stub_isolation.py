#!/usr/bin/env python3
"""A stub installed by one test module must not leak into the next.

THE PROBLEM
-----------
Several test files install synthetic modules at import time and never remove them:

    sys.modules["queue_counters"] = types.ModuleType("queue_counters")

conftest already restored five hardcoded names (db, kill_switch, log,
subscription_guard, provider_terms). Everything else stayed stubbed for the rest of the
session, and the resulting failures are order-dependent — a file passes alone and fails
in the suite, or the reverse. That is the most expensive kind of test failure to
diagnose, because the test that fails is not the test that is broken.

Both of these were hit while working the queue this file came from:

  * test_scoreboard_history.py stubs `queue_counters`; a later module importing it got
    the stub and died reading any attribute off it during collection.
  * a module leaves patched state on `claude_cli`; a later file driving it saw
    StopIteration from an exhausted mock instead of a result.

conftest now evicts generically instead of maintaining a list. These tests hold that
behaviour in place.

NAMING
------
`test_zz_` so default alphabetical collection puts it after the polluting modules —
this file is only meaningful when something ran before it. It does not depend on that
ordering to pass (it installs its own stub too), but the realistic case is the one
worth exercising.
"""
import os
import sys
import types

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNNER = os.path.dirname(_HERE)
sys.path.insert(0, _RUNNER)


def _suite_conftest():
    """The already-loaded runner/tests/conftest.py.

    `import conftest` resolves to the REPO-ROOT conftest.py, which has no
    _restore_real_modules — pytest has already imported this suite's conftest under a
    rootdir-dependent module name, so it is fetched from sys.modules by file path
    rather than re-imported (re-importing would create a second copy with its own
    _REAL_MODULES and test nothing).
    """
    target = os.path.join(_HERE, "conftest.py")
    for module in list(sys.modules.values()):
        if getattr(module, "__file__", None) and \
                os.path.abspath(module.__file__) == target:
            return module
    pytest.skip("suite conftest not importable under this rootdir")


_conftest = _suite_conftest()


# ── the real-world case ─────────────────────────────────────────────────────

def test_queue_counters_resolves_to_the_real_module():
    """test_scoreboard_history stubs this one. If eviction regresses, this fails."""
    import queue_counters
    assert getattr(queue_counters, "__file__", None), \
        "queue_counters is a stub left behind by an earlier test module"
    assert hasattr(queue_counters, "QUEUE_STATES")


def test_claude_cli_resolves_to_the_real_module():
    import claude_cli
    assert getattr(claude_cli, "__file__", None)
    assert hasattr(claude_cli, "run")


# ── the eviction itself ─────────────────────────────────────────────────────

def test_a_stub_shadowing_a_runner_module_is_evicted():
    sys.modules["queue_counters"] = types.ModuleType("queue_counters")
    _conftest._restore_real_modules()
    assert "queue_counters" not in sys.modules or \
        getattr(sys.modules["queue_counters"], "__file__", None)


def test_eviction_makes_the_next_import_real():
    sys.modules["queue_counters"] = types.ModuleType("queue_counters")
    _conftest._restore_real_modules()
    import queue_counters
    assert hasattr(queue_counters, "QUEUE_STATES")


def test_a_real_module_is_never_evicted():
    """Eviction keys on 'no __file__', so a genuinely imported module is untouched."""
    import queue_counters
    before = queue_counters
    _conftest._restore_real_modules()
    import queue_counters as after
    assert after is before


def test_a_stub_that_shadows_nothing_is_left_alone():
    """Only names matching a real runner/<name>.py are evicted."""
    name = "definitely_not_a_runner_module_xyz"
    sys.modules[name] = types.ModuleType(name)
    try:
        _conftest._restore_real_modules()
        assert name in sys.modules
    finally:
        sys.modules.pop(name, None)


def test_the_hardcoded_control_plane_modules_are_still_restored():
    """The original five must keep being replaced, not evicted."""
    sys.modules["db"] = types.ModuleType("db")
    _conftest._restore_real_modules()
    assert getattr(sys.modules["db"], "__file__", None)


def test_submodules_are_not_touched():
    """A dotted name is a package member, not a runner top-level module."""
    name = "queue_counters.sub"
    sys.modules[name] = types.ModuleType(name)
    try:
        _conftest._restore_real_modules()
        assert name in sys.modules
    finally:
        sys.modules.pop(name, None)


def test_eviction_is_idempotent():
    _conftest._restore_real_modules()
    _conftest._restore_real_modules()
    import queue_counters
    assert hasattr(queue_counters, "QUEUE_STATES")


def test_eviction_does_not_raise_on_odd_sys_modules_entries():
    """sys.modules can hold None and non-module objects; eviction must not care."""
    sys.modules["_odd_entry_for_test"] = None
    try:
        _conftest._restore_real_modules()
    finally:
        sys.modules.pop("_odd_entry_for_test", None)
