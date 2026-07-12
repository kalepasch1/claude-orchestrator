#!/usr/bin/env python3
"""
nightly_cheap_sweep.py — batch mechanical/doc/test tasks to the cheapest providers
during off-peak hours so daytime capacity is reserved for high-value feature work.

How it works:
  1. Checks if current time is within the configured off-peak window (default 22:00–06:00 local).
  2. Finds QUEUED tasks whose kind is mechanical, doc, test, or lint — the cheap long tail.
  3. Forces their model to ORCH_DEFAULT_MODEL (Haiku) regardless of any prior routing.
  4. Optionally batches them via batch_mechanical if eligible.
  5. Boosts their confidence (priority proxy) so the runner picks them up next.

This is a periodic job — register in periodic.py as "nightsweep".

Env knobs:
  ORCH_NIGHT_START       hour (0-23) when off-peak begins, default 22
  ORCH_NIGHT_END         hour (0-23) when off-peak ends, default 6
  ORCH_NIGHT_SWEEP_MAX   max tasks to sweep per run, default 30
  ORCH_NIGHT_MODEL       model to force for swept tasks, default ORCH_DEFAULT_MODEL
  ORCH_NIGHT_SWEEP_ENABLED  master switch, default true
"""
import os, sys, time, json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

NIGHT_START = int(os.environ.get("ORCH_NIGHT_START", "22"))
NIGHT_END = int(os.environ.get("ORCH_NIGHT_END", "6"))
SWEEP_MAX = int(os.environ.get("ORCH_NIGHT_SWEEP_MAX", "30"))
NIGHT_MODEL = os.environ.get("ORCH_NIGHT_MODEL", "") or os.environ.get("ORCH_DEFAULT_MODEL", "claude-haiku-4-5-20251001")
ENABLED = os.environ.get("ORCH_NIGHT_SWEEP_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Task kinds eligible for cheap overnight processing
CHEAP_KINDS = {"mechanical", "doc", "test", "lint", "format", "chore", "docs", "rename"}

# Prompt patterns that signal cheap/mechanical work (subset of model_router.MECHANICAL)
CHEAP_PATTERNS = (
    "rename", "format", "lint", "typo", "comment", "docstring",
    "whitespace", "import order", "changelog", "bump version",
    "copy edit", "test coverage", "add test", "unit test",
    "documentation", "readme", "spelling",
)


def is_off_peak(now=None):
    """Return True if current hour is within the off-peak window."""
    h = (now or datetime.now()).hour
    if NIGHT_START > NIGHT_END:
        # Window wraps midnight (e.g. 22:00–06:00)
        return h >= NIGHT_START or h < NIGHT_END
    else:
        return NIGHT_START <= h < NIGHT_END


def _is_cheap_task(task):
    """True if this task is eligible for cheap overnight processing."""
    kind = (task.get("kind") or "").lower().strip()
    if kind in CHEAP_KINDS:
        return True
    prompt = (task.get("prompt") or "").lower()
    if len(prompt) > 800:
        return False  # long prompts are likely substantive
    return any(p in prompt for p in CHEAP_PATTERNS)


def find_sweepable():
    """Find QUEUED tasks eligible for cheap overnight processing."""
    tasks = db.select("tasks", {
        "select": "id,slug,prompt,kind,state,project_id,model",
        "state": "eq.QUEUED",
        "limit": str(SWEEP_MAX * 3),  # fetch more than needed, filter locally
    }) or []
    eligible = []
    for t in tasks:
        if _is_cheap_task(t):
            eligible.append(t)
        if len(eligible) >= SWEEP_MAX:
            break
    return eligible


def sweep():
    """Main entry: force cheap tasks to the cheapest model during off-peak hours.
    Returns a summary dict."""
    if not ENABLED:
        return {"status": "disabled", "swept": 0}

    if not is_off_peak():
        return {"status": "not_off_peak", "hour": datetime.now().hour, "swept": 0}

    eligible = find_sweepable()
    if not eligible:
        return {"status": "no_eligible_tasks", "swept": 0}

    swept = 0
    for t in eligible:
        current_model = t.get("model") or ""
        if current_model == NIGHT_MODEL:
            # Already on cheapest model, just boost priority
            try:
                db.update("tasks", {"id": t["id"]}, {
                    "confidence": 0.95,  # high confidence = high priority in ev_scheduler
                    "updated_at": "now()",
                })
                swept += 1
            except Exception:
                pass
        else:
            try:
                db.update("tasks", {"id": t["id"]}, {
                    "model": NIGHT_MODEL,
                    "confidence": 0.95,
                    "note": f"[night-sweep] rerouted from {current_model or 'default'} to {NIGHT_MODEL}",
                    "updated_at": "now()",
                })
                swept += 1
            except Exception:
                pass

    # Heartbeat
    try:
        db.insert("controls", {
            "key": "NIGHT_SWEEP_LAST_RUN",
            "value": json.dumps({
                "swept": swept,
                "total_eligible": len(eligible),
                "model": NIGHT_MODEL,
                "hour": datetime.now().hour,
                "ts": time.time(),
            }),
            "updated_at": "now()",
        }, upsert=True)
    except Exception:
        pass

    return {"status": "ok", "swept": swept, "total_eligible": len(eligible), "model": NIGHT_MODEL}


def run():
    """Periodic entry point."""
    result = sweep()
    print(f"nightly_cheap_sweep: {result}")
    return result


# --- Tests ---

def _test_is_off_peak():
    from datetime import datetime as dt
    # 22:00–06:00 window
    assert is_off_peak(dt(2026, 1, 1, 23, 0)) is True
    assert is_off_peak(dt(2026, 1, 1, 3, 0)) is True
    assert is_off_peak(dt(2026, 1, 1, 12, 0)) is False
    assert is_off_peak(dt(2026, 1, 1, 22, 0)) is True
    assert is_off_peak(dt(2026, 1, 1, 6, 0)) is False
    assert is_off_peak(dt(2026, 1, 1, 21, 59)) is False
    print("PASS: _test_is_off_peak")


def _test_is_cheap_task():
    assert _is_cheap_task({"kind": "mechanical", "prompt": ""}) is True
    assert _is_cheap_task({"kind": "doc", "prompt": ""}) is True
    assert _is_cheap_task({"kind": "test", "prompt": ""}) is True
    assert _is_cheap_task({"kind": "build", "prompt": "rename the variable"}) is True
    assert _is_cheap_task({"kind": "build", "prompt": "design a new distributed settlement engine with crypto auth"}) is False
    assert _is_cheap_task({"kind": "build", "prompt": "x" * 900}) is False  # too long
    assert _is_cheap_task({"kind": "lint", "prompt": ""}) is True
    assert _is_cheap_task({"kind": "feature", "prompt": "add unit test for parser"}) is True
    print("PASS: _test_is_cheap_task")


def _test_sweep_disabled():
    import nightly_cheap_sweep as ncs
    orig = ncs.ENABLED
    ncs.ENABLED = False
    assert ncs.sweep()["status"] == "disabled"
    ncs.ENABLED = orig
    print("PASS: _test_sweep_disabled")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        _test_is_off_peak()
        _test_is_cheap_task()
        _test_sweep_disabled()
        print("All nightly_cheap_sweep tests passed.")
    else:
        run()
