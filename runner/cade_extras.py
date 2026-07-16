#!/usr/bin/env python3
"""
cade_extras.py - harness that auto-discovers and runs all cx_*.py modules.

Each cx_*.py module in the runner/ directory must expose a run() function.
One bad module never breaks the loop; failures are logged and skipped.
"""
import os, sys, glob, importlib, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
_loaded_modules = {}


def _discover():
    """Return sorted list of cx_*.py basenames (without .py)."""
    pattern = os.path.join(_RUNNER_DIR, "cx_*.py")
    return sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(pattern)
    )


def _load(name):
    """Import (or return cached) a cx_ module by name."""
    if name in _loaded_modules:
        return _loaded_modules[name]
    mod = importlib.import_module(name)
    _loaded_modules[name] = mod
    return mod


def run():
    """Discover and execute all cx_*.py modules. Fail-soft: log and continue on error."""
    modules = _discover()
    if not modules:
        print("cade_extras: no cx_* modules found")
        return {"ran": 0, "failed": 0}

    ran = 0
    failed = 0
    for name in modules:
        try:
            mod = _load(name)
            mod.run()
            ran += 1
            print(f"cade_extras: {name} OK")
        except Exception as e:
            failed += 1
            print(f"cade_extras: {name} FAILED: {e}")
            traceback.print_exc()

    print(f"cade_extras: {ran} ran, {failed} failed")
    return {"ran": ran, "failed": failed}


if __name__ == "__main__":
    run()
