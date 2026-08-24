"""Repo-root conftest: make the `runner` PACKAGE authoritative for the whole suite.

Why this file exists
--------------------
The suite has two import conventions that collide:

  * `tests/*.py` do `sys.path.insert(0, <repo>/runner)` and then import the
    control-plane modules flat (`import db`, `import log`, ...). That is also what
    `runner/tests/conftest.py` relies on.
  * Other `tests/*.py` import through the package (`from runner.scope_gate import ...`).

Once `<repo>/runner` sits at sys.path[0], the module file `runner/runner.py`
shadows the `runner/` package. Every package-style import then fails at COLLECTION
time with either

    ModuleNotFoundError: No module named 'runner.scope_gate'; 'runner' is not a package
    ImportError: cannot import name 'prompt_evolver' from 'runner' (.../runner/runner.py)

and pytest aborts the entire session ("Interrupted: N errors during collection"),
so all ~5.7k otherwise-passing tests never run. The shadowing is order-dependent,
which is why it looks like a flaky, file-count-dependent failure.

Binding the real package into `sys.modules["runner"]` here — before any test module
is imported — closes the hole permanently. A later `sys.path.insert` cannot rebind
an already-imported module, so both conventions now work side by side.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_RUNNER_DIR = _REPO_ROOT / "runner"

# Repo root must come FIRST so the `runner/` package wins over `runner/runner.py`.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
elif sys.path.index(str(_REPO_ROOT)) != 0:
    sys.path.remove(str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT))

# The flat control-plane modules (db, log, kill_switch, ...) still need runner/ on
# the path, but only as a fallback — hence append rather than insert.
if _RUNNER_DIR.is_dir() and str(_RUNNER_DIR) not in sys.path:
    sys.path.append(str(_RUNNER_DIR))


def _load_runner_package():
    """Import runner/__init__.py directly, bypassing sys.path resolution.

    Going through `import runner` would re-lose the race: by the time this runs a
    test may already have put `<repo>/runner` at sys.path[0], and the import would
    resolve to runner/runner.py all over again. Loading from the known file path is
    order-independent.
    """
    init = _RUNNER_DIR / "__init__.py"
    if not init.is_file():
        return None
    existing = sys.modules.get("runner")
    if existing is not None and getattr(existing, "__path__", None):
        return existing
    sys.modules.pop("runner", None)
    try:
        spec = importlib.util.spec_from_file_location(
            "runner", init, submodule_search_locations=[str(_RUNNER_DIR)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["runner"] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        # Never let path repair take the suite down; the individual test that needs
        # the package will report its own, far more actionable, import error.
        sys.modules.pop("runner", None)
        if existing is not None:
            sys.modules["runner"] = existing
        return None


_RUNNER_PACKAGE = _load_runner_package()


def _rebind_runner_package() -> None:
    """Undo `runner` -> runner/runner.py shadowing introduced by a prior test module.

    Tests under runner/tests/ import the control plane flat, and some of them import
    the `runner.py` entrypoint itself — which rebinds sys.modules['runner'] to a
    plain module. Any test module collected afterwards that does
    `from runner.<mod> import ...` then fails to even import. Restoring the package
    before each collection closes that window; modules that already bound their own
    reference to runner.py keep working, exactly as with the same pattern in
    runner/tests/conftest.py.
    """
    if _RUNNER_PACKAGE is None:
        return
    current = sys.modules.get("runner")
    if current is not _RUNNER_PACKAGE and not getattr(current, "__path__", None):
        sys.modules["runner"] = _RUNNER_PACKAGE


def pytest_collectstart(collector) -> None:
    _rebind_runner_package()
    _evict_leaked_doubles()


# ─────────────────────────────────────────────────────────────────────────────
# Leaked test doubles in sys.modules
#
# runner/tests/conftest.py restores real control-plane modules at module boundaries, but
# it only governs runner/tests/. The 152 test files at runner/*.py are collected by this
# repo-root conftest and by nothing else, and one of them leaks:
# test_canary_ollama_22.py runs `patch.dict(sys.modules, {"db": MagicMock()})` inside five
# concurrent threads, and patch.dict restores by clearing and re-filling the dict — so
# interleaved restores park the mock in sys.modules["db"] for the rest of the session.
#
# From then on every `@patch("db.select")` patches the leftover mock while the real db
# module runs unpatched and reaches for a live database. The symptom lands on unrelated
# files much later (17 tests in test_canary_ollama_23, 5 in test_done_to_merged_conversion,
# and others), each of which passes perfectly in isolation.
#
# Only MOCK-shaped stand-ins are evicted. A `types.ModuleType` fake installed at import
# time is the deliberate convention in this suite and is left alone.
# ─────────────────────────────────────────────────────────────────────────────
import types as _types


def _is_mock_double(module) -> bool:
    """True for a sys.modules entry that is not a module at all.

    A MagicMock answers getattr(m, "__file__") with another Mock, so a __file__ check reads
    it as a real module and leaves it in place. Type is the only reliable signal.
    """
    return not isinstance(module, _types.ModuleType)


#: The real module object for every runner/ module we have seen imported. Restoring THIS
#: object matters: popping the name instead would make the next `import db` build a fresh
#: module, and a test that patched attributes on the object it imported at module scope
#: would be patching a different db than the code under test now sees.
_REAL_BY_NAME: dict = {}


def _remember_real_modules() -> None:
    for name, module in list(sys.modules.items()):
        if "." in name or module is None or _is_mock_double(module):
            continue
        if not getattr(module, "__file__", None):
            continue
        try:
            if Path(module.__file__).resolve().parent != _RUNNER_DIR:
                continue
        except Exception:
            continue
        _REAL_BY_NAME.setdefault(name, module)


def _evict_leaked_doubles() -> None:
    _remember_real_modules()
    for name, module in list(sys.modules.items()):
        if "." in name or module is None or not _is_mock_double(module):
            continue
        if not (_RUNNER_DIR / f"{name}.py").is_file():
            continue
        real = _REAL_BY_NAME.get(name)
        if real is not None:
            sys.modules[name] = real
        else:
            sys.modules.pop(name, None)


try:  # pytest is present whenever this file is loaded; guard only for direct import
    import pytest as _pytest

    @_pytest.fixture(autouse=True)
    def _restore_environment_after_every_test():
        """A test's env overrides must not reach the next test.

        runner/tests/conftest.py has had this for a while, but it governs runner/tests/
        only — and the 152 test files at runner/*.py, collected by this conftest and
        nothing else, had no environment isolation at all. One file setting a routing kill
        switch or a threshold and not putting it back silently changed the answer for
        every file collected afterwards, which is why so many of them pass alone and fail
        in a full run.
        """
        before = dict(os.environ)
        yield
        os.environ.clear()
        os.environ.update(before)

    @_pytest.fixture(autouse=True)
    def _evict_leaked_module_doubles():
        """Put back any real module a test swapped for a Mock and did not restore.

        A module-boundary restore is too coarse for a double leaked INSIDE a test — a
        threaded patch.dict whose restores interleave, or a test that raises before its
        context manager unwinds. Those leak for the rest of the session.
        """
        yield
        _evict_leaked_doubles()
except ImportError:  # pragma: no cover
    pass
