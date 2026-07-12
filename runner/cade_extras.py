#!/usr/bin/env python3
"""
cade_extras.py - CADE Extensions Harness.

Globs runner/cx_*.py, imports each, and calls its run() inside try/except.
One bad module must never break the loop; failures are logged.
Wired as "cadeextras" in periodic.py's JOBS map + a daily schedule row in runner.py.
"""
import os, sys, glob, importlib, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))


def run():
    """Discover and run all cx_*.py modules in the runner directory."""
    pattern = os.path.join(RUNNER_DIR, "cx_*.py")
    modules = sorted(glob.glob(pattern))
    results = {}
    errors = []

    for mod_path in modules:
        mod_name = os.path.splitext(os.path.basename(mod_path))[0]
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "run") and callable(mod.run):
                result = mod.run()
                results[mod_name] = {"ok": True, "result": result}
                print(f"cade_extras: {mod_name}.run() succeeded")
            else:
                results[mod_name] = {"ok": False, "error": "no run() function"}
                print(f"cade_extras: {mod_name} has no run() function, skipping")
        except Exception as e:
            tb = traceback.format_exc()
            results[mod_name] = {"ok": False, "error": str(e)[:500]}
            errors.append(mod_name)
            print(f"cade_extras: {mod_name}.run() FAILED: {e}\n{tb[:800]}")

    n_ok = sum(1 for r in results.values() if r.get("ok"))
    n_fail = len(errors)
    print(f"cade_extras: ran {len(results)} modules, {n_ok} ok, {n_fail} failed"
          + (f" ({', '.join(errors)})" if errors else ""))
    return {"total": len(results), "ok": n_ok, "failed": n_fail, "errors": errors}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
