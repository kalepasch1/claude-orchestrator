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
