#!/usr/bin/env python3
"""static_sanity.py — undefined-name gate for the runner's critical loops.

WHY (2026-07-31): `_already_integrated` was dropped by an overwrite while its
call site survived. Python only raises NameError at CALL time, the per-project
error isolation swallowed it, and every merge pass silently produced
"0 merged" for three days — the no-prod-deploys incident. pyflakes catches
"undefined name" STATICALLY. This module makes that check a standing gate:

  * check(paths) -> list of "file:line undefined name 'x'" strings
  * assert_critical() -> called at merge_train/runner startup; if a CRITICAL
    module has an undefined name it prints CRITICAL, files a coordination
    alert, and raises — a loop that would silently no-op must refuse to start.

Fail-soft on tooling absence: if pyflakes is not installed the gate logs once
and passes (never wedge the fleet on a missing dev tool), but the sentinel
reports the missing tool so it gets installed.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

CRITICAL_MODULES = [
    "merge_train.py", "integration_runtime.py", "runner.py", "db.py",
    "fleet_control.py", "verify.py", "auto_remediate.py", "release_train.py",
    "blocked_triage.py", "intake_watcher.py", "swarm_executor.py",
    "model_gateway.py", "preflight_filter.py", "parallel_dispatch.py",
    # ADDED 2026-08-12. Both modules are crash-free-until-used dispatchers, which is
    # exactly the shape audit() catches and assert_critical() was not looking at:
    #   * periodic.py owns the job dispatch table, so one dropped definition takes out
    #     every job in it at once — `run_editorial` is not defined crash-looped eleven
    #     jobs, and crash_loop_detector.py:272 still carries the note about it.
    #   * canary.py gates deploys. It shipped six undefined-name findings for `_log`
    #     (canary.py:69,72,74,85,88,90) that audit() reported for days while the gate
    #     stayed silent, because the file was not on this list.
    # Both are clean as of this commit, so adding them cannot wedge startup today; the
    # point is that the next dropped definition refuses to start instead of no-opping.
    "periodic.py", "canary.py",
]


def all_modules():
    """Every runner module, excluding tests.

    WHY (2026-08-02): the gate only ever covered the 14 names above, so undefined names went on
    shipping everywhere else. A sweep of the full tree found 42 of them across nine modules —
    including blocker_quarantine's `max_depth`, which crash-looped the quarantine job for weeks,
    and whole missing functions in config_sync, ci_dispatch and promotion_pipeline. Those are the
    same "overwrite dropped the definition, the call site survived" failure this module was
    written to stop; it just wasn't looking at those files. audit() below covers the whole tree so
    the sentinel can report drift outside the critical set without gating startup on it.
    """
    return sorted(
        os.path.join(HERE, n) for n in os.listdir(HERE)
        if n.endswith(".py") and not n.startswith("test_")
    )


def audit():
    """Undefined-name findings across the entire runner tree. Returns [] clean, None if no tool."""
    return check(all_modules())


def _pyflakes(paths):
    try:
        r = subprocess.run([sys.executable, "-m", "pyflakes", *paths],
                           capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if r.returncode in (0, 1):
        return r.stdout or ""
    return None


def check(paths=None):
    """Return undefined-name findings for the given (or all critical) modules."""
    if paths is None:
        paths = [os.path.join(HERE, m) for m in CRITICAL_MODULES]
    paths = [p for p in paths if os.path.exists(p)]
    out = _pyflakes(paths)
    if out is None:
        return None  # tooling unavailable — caller decides
    return [l for l in out.splitlines() if "undefined name" in l]


def assert_critical(caller="startup"):
    """Refuse to start a critical loop whose own code has undefined names."""
    findings = check()
    if findings is None:
        if not getattr(assert_critical, "_warned", False):
            assert_critical._warned = True
            print("static_sanity: pyflakes unavailable — undefined-name gate "
                  "SKIPPED (install: pip3 install --user pyflakes)", flush=True)
        return True
    if findings:
        msg = f"static_sanity[{caller}]: CRITICAL undefined names: " + "; ".join(findings[:10])
        print(msg, flush=True)
        try:
            sys.path.insert(0, HERE)
            import db
            db.insert("coordination_tasks", {
                "task_type": "static_sanity_alert",
                "payload": json.dumps({
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "caller": caller, "findings": findings[:20]})[:8000]},
                      upsert=False)
        except Exception:
            pass
        raise RuntimeError(msg)
    return True


if __name__ == "__main__":
    f = check()
    if f is None:
        print("pyflakes unavailable"); sys.exit(2)
    print("\n".join(f) if f else "clean")
    sys.exit(1 if f else 0)
