"""Suite-wide isolation for tests/ — keeps a mocked `db` from leaking between files.

THE BUG THIS FIXES. Thirteen tests in this directory passed in isolation and failed
in the full run:

    AttributeError: <module 'db'> has no attribute 'update'
    AttributeError: module 'db' has no attribute 'TransientDBError'

runner/db.py defines both. The module under test was not runner/db.py at all — it was
a MagicMock. tests/test_failure_forecast.py and tests/test_patch_templates_lookup.py
do `sys.modules["db"] = <mock>` at IMPORT time and never put the real one back, so
every file collected after them in the same session inherited the mock. Which files
broke depended on collection order, which is why the sweeper and materializer suites
looked flaky rather than wrong.

runner/tests/ already has a conftest.py doing this class of restoration; tests/ had
none. This is the missing half.

The pin happens per-test rather than once at session start because the mocks are
installed during COLLECTION, i.e. before any fixture runs — restoring once up front
would simply be overwritten again. Tests that genuinely want a mocked db install it
inside the test (or keep the module-level reference they captured at import, which
this fixture does not touch).
"""
import importlib
import os
import sys

import pytest

_RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)


def _load_real_db():
    """Import runner/db.py under a private name so importing it cannot itself be
    satisfied by whatever mock currently occupies sys.modules['db']."""
    path = os.path.join(_RUNNER, "db.py")
    if not os.path.exists(path):
        return None
    cached = sys.modules.get("_real_runner_db")
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location("_real_runner_db", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_real_runner_db"] = module  # registered before exec for re-entrancy
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - a broken db must not break collection
        sys.modules.pop("_real_runner_db", None)
        return None
    return module


def _is_mocked(module):
    """A real module was loaded from a file; a MagicMock has no meaningful __file__."""
    return not isinstance(getattr(module, "__file__", None), str)


@pytest.fixture(autouse=True)
def _real_db_module():
    previous = sys.modules.get("db")
    if previous is None or _is_mocked(previous):
        real = _load_real_db()
        if real is not None:
            sys.modules["db"] = real
    try:
        yield
    finally:
        # Restore exactly what was there, including "nothing".
        if previous is None:
            sys.modules.pop("db", None)
        else:
            sys.modules["db"] = previous
