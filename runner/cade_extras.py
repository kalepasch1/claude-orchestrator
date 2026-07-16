"""
cade_extras.py — harness that auto-discovers and runs all runner/cx_*.py modules.

Globs runner/cx_*.py, imports each, and calls its run() inside try/except.
One bad module must never break the loop; failures are logged and counted.
"""
import glob
import importlib
import logging
import os
import traceback

log = logging.getLogger(__name__)

_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))


def run():
    """Discover and execute all cx_* modules. Returns (success_count, failure_count)."""
    pattern = os.path.join(_RUNNER_DIR, "cx_*.py")
    modules = sorted(glob.glob(pattern))

    if not modules:
        log.info("cade_extras: no cx_* modules found")
        return 0, 0

    success = 0
    failure = 0

    for mod_path in modules:
        mod_name = os.path.splitext(os.path.basename(mod_path))[0]
        try:
            mod = importlib.import_module(mod_name)
            if not hasattr(mod, "run"):
                log.warning("cade_extras: %s has no run() — skipping", mod_name)
                continue
            log.info("cade_extras: running %s", mod_name)
            mod.run()
            success += 1
        except Exception:
            failure += 1
            log.error(
                "cade_extras: %s failed:\n%s", mod_name, traceback.format_exc()
            )

    log.info(
        "cade_extras: finished — %d succeeded, %d failed out of %d modules",
        success, failure, len(modules),
    )
    return success, failure
