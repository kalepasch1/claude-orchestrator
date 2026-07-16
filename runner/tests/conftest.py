# conftest.py provides shared fixtures for all runner tests.
"""Suite-wide isolation for tests that mutate process-global state."""
import os
import sys
import pytest

import db as _real_db
import kill_switch as _real_kill_switch
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


@pytest.hookimpl(hookwrapper=True)
def pytest_pycollect_makemodule(module_path, parent):
    """Prevent synthetic control-plane modules from leaking into later modules."""
    yield
    sys.modules["db"] = _real_db
    sys.modules["kill_switch"] = _real_kill_switch
    sys.modules["subscription_guard"] = _real_subscription_guard
    sys.modules["provider_terms"] = _real_provider_terms
