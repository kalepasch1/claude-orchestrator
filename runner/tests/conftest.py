"""Suite-wide isolation for tests that mutate process-global state."""
import os
import sys
import pytest

import db as _real_db
import kill_switch as _real_kill_switch
import log as _real_log
import subscription_guard as _real_subscription_guard
import provider_terms as _real_provider_terms

_PROVIDER_DEFAULTS = {
    name: dict(metadata) for name, metadata in _real_provider_terms.DEFAULTS.items()
}


@pytest.fixture(autouse=True)
def _restore_environment_after_test():
    """A test's routing/config overrides must never affect later tests."""
    before = dict(os.environ)
    _real_provider_terms.DEFAULTS.clear()
    _real_provider_terms.DEFAULTS.update(
        {name: dict(metadata) for name, metadata in _PROVIDER_DEFAULTS.items()}
    )
    sys.modules["provider_terms"] = _real_provider_terms
    yield
    os.environ.clear()
    os.environ.update(before)


# Every control-plane module any test replaces via sys.modules[...] = ModuleType(...)
# must be listed here, or it leaks into every module imported afterwards.
# Keep in sync with:  grep -rhoE 'sys\.modules\["[a-z_]+"\] *=' runner/tests/*.py
_REAL_MODULES = {
    "db": _real_db,
    "kill_switch": _real_kill_switch,
    "log": _real_log,
    "subscription_guard": _real_subscription_guard,
    "provider_terms": _real_provider_terms,
}


def _restore_real_modules():
    sys.modules.update(_REAL_MODULES)


@pytest.hookimpl(hookwrapper=True)
def pytest_pycollect_makemodule(module_path, parent):
    """Prevent synthetic control-plane modules from leaking into later modules."""
    yield
    _restore_real_modules()


@pytest.hookimpl(hookwrapper=True)
def pytest_collectstart(collector):
    """Restore real control-plane modules BEFORE each test module is imported.

    Several modules (test_hive_candidates_ops_page, test_source_config_validator)
    install a synthetic `db` at import time via sys.modules["db"] = ModuleType("db").
    pytest_pycollect_makemodule alone is not enough: under pytest 8 the module body
    executes in Module.collect(), i.e. AFTER that hook's post-yield restore. So the
    fake `db` leaked into every module imported afterwards, and any later
    `from db import <name>` died with "cannot import name ... (unknown location)".

    That made whole-suite collection fail while each file passed in isolation —
    which silently broke the merge gate (pytest) for every branch. Restoring on
    collectstart closes the window. Rebinding sys.modules does not affect modules
    that already bound their own reference at import, so the polluting tests keep
    working against their fakes.
    """
    if isinstance(collector, pytest.Module):
        _restore_real_modules()
    yield
