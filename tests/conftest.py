"""Extend the hermetic guard to the repo-root `tests/` tree.

WHY THIS FILE EXISTS
--------------------
`runner/tests/conftest.py` blocks outbound sockets so a unit test cannot depend on a
remote host. It is scoped to its own directory, so the ~100 test files under `tests/` had
no guard at all — and that is where a real provider call gets made. The observed failure
was `litellm` / `llm.APIError` with an XaiException 403 (permission denied / credits
spent): a unit test reaching a live vendor endpoint, then failing for a reason that has
nothing to do with the code under test. The same run would pass or fail depending on
someone else's billing.

REUSE, NOT A SECOND COPY
------------------------
The guard is imported from `runner/tests/conftest.py` rather than reimplemented. Two
copies of a security-shaped rule drift apart, and the version that stops blocking is the
one nobody notices. Everything the guard has learned — refusing with ECONNREFUSED so
fail-soft callers take the branch they would really take, pointing child processes at the
discard port so git does not pay GitHub latency, bounding unbounded subprocesses with a
warning instead of a failure — is inherited automatically.

OPTING OUT
----------
A test that genuinely needs a socket marks itself:

    @pytest.mark.allow_network
    def test_against_the_real_thing(): ...

Integration tests that need credentials should ALSO gate on them, so the default `pytest`
run skips rather than fails:

    pytestmark = pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="integration test; set RUN_INTEGRATION_TESTS=1 to run",
    )
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUNNER_CONFTEST = os.path.join(_REPO, "runner", "tests", "conftest.py")

#: Env var that opts a test file in to running against real credentials.
INTEGRATION_ENV = "RUN_INTEGRATION_TESTS"


def _load_runner_conftest():
    """Import runner/tests/conftest.py as a module. None when unavailable.

    Fail-soft: if it cannot be loaded, this file must not break collection of the
    hundred test files that live beside it. The guard is a safety net, not a dependency.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "_runner_tests_conftest", _RUNNER_CONFTEST)
        if spec is None or spec.loader is None:
            return None
        module = sys.modules.get("_runner_tests_conftest")
        if module is None:
            module = importlib.util.module_from_spec(spec)
            sys.modules["_runner_tests_conftest"] = module
            spec.loader.exec_module(module)
        return module
    except Exception:
        return None


_runner_conftest = _load_runner_conftest()

# Re-export so a test in this tree can assert on the same exception type the guard raises.
NetworkAccessInTest = getattr(_runner_conftest, "NetworkAccessInTest", ConnectionRefusedError)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_network: this test genuinely needs a real socket; do not block it.",
    )
    config.addinivalue_line(
        "markers",
        f"integration: needs real credentials; set {INTEGRATION_ENV}=1 to run.",
    )


def pytest_collection_modifyitems(config, items):
    """Skip `integration`-marked tests unless RUN_INTEGRATION_TESTS=1.

    Skipped, not failed. A suite that is red on arrival for everyone without credentials
    teaches people to ignore it — the same reasoning the CI workflow already applies when
    SUPABASE_URL is absent.
    """
    if os.environ.get(INTEGRATION_ENV) == "1":
        return
    skip = pytest.mark.skip(
        reason=f"integration test; set {INTEGRATION_ENV}=1 to run against real services")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)


if _runner_conftest is not None and hasattr(_runner_conftest, "_hermetic"):
    # The autouse fixture itself, reused verbatim. pytest binds it to this directory.
    _hermetic = _runner_conftest._hermetic
