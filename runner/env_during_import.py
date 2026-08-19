#!/usr/bin/env python3
"""Set environment variables for the duration of a module import, then put them back.

Several runner modules bind a feature flag to a module-level constant at import:

    ENABLED = os.environ.get("ORCH_X_ENABLED", "false").lower() == "true"

so a test for that module has to set the variable BEFORE importing it. The obvious way —
`os.environ["ORCH_X_ENABLED"] = "true"` at the top of the test file — works for that file
and quietly breaks every file after it. pytest imports every test module during COLLECTION,
before any fixture runs, so the assignment is not scoped to the test module: it rewrites the
variable for the whole process, and conftest.py's per-test environment restore cannot undo
it (the pollution is already inside the snapshot it takes).

That cost a full session on 2026-08-18 — ORCH_DELIVERY_LEASE_REQUIRED, ORCH_SHADOW_MODE and
the Supabase credentials each leaked this way, and each looked like a product regression:
green standalone, red in the release canary.

    # before                          # after
    os.environ["ORCH_X"] = "true"     mod = import_with_env("mod", ORCH_X="true")
    import mod

The module still sees the value at import; the process does not keep it.
"""
import contextlib
import importlib
import os


@contextlib.contextmanager
def during_import(**pairs):
    """Set env vars for the block, restoring prior values — including 'was absent'."""
    saved = {key: os.environ.get(key) for key in pairs}
    try:
        for key, value in pairs.items():
            os.environ[key] = str(value)
        yield
    finally:
        for key, previous in saved.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def import_with_env(module_name, **pairs):
    """Import (or re-import) `module_name` with `pairs` set, then restore the environment.

    Returns the module. Already-imported modules are reloaded so the constants are rebound
    under the requested values rather than whatever the first importer happened to see.
    """
    with during_import(**pairs):
        module = importlib.import_module(module_name)
        return importlib.reload(module)
