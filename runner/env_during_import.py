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
import sys


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
    """Import a PRIVATE copy of `module_name` with `pairs` set, then restore everything.

    Returns the fresh module, whose constants are bound under the requested values. The
    environment is restored, and so is sys.modules: any module that already imported
    `module_name` keeps the object it has, and the next plain `import module_name`
    anywhere gets that same original back.

    The obvious implementation is `importlib.reload(importlib.import_module(name))`, and it
    reintroduces the exact bug this file exists to fix, one layer down. reload() mutates the
    module object IN PLACE, so it rebinds the constants for every holder of that object, for
    the rest of the process — and pytest imports all test modules during collection, so the
    rebinding happens before a single test runs.

    Concretely: semantic_merge._ENABLED defaults TRUE; test_semantic_merge.py imports it
    with ORCH_SEMANTIC_MERGE="false"; five other modules that import semantic_merge then saw
    the feature switched off for the whole session. Same class of failure as the raw
    os.environ assignment — green standalone, red in the release canary — just harder to
    find, because the line that causes it looks like the fix.

    A private copy costs one extra module execution and cannot leak: the test holds the only
    reference to it.
    """
    with during_import(**pairs):
        previous = sys.modules.pop(module_name, None)
        try:
            fresh = importlib.import_module(module_name)
        finally:
            # Unconditional: put the shared entry back whether the import raised or not.
            # Leaving a half-built module (or nothing) in sys.modules under a name other
            # code imports is worse than the flag leak.
            if previous is not None:
                sys.modules[module_name] = previous
            else:
                sys.modules.pop(module_name, None)
        return fresh
