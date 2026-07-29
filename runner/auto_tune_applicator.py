#!/usr/bin/env python3
"""
auto_tune_applicator.py — reads tuning decisions from resource_events and
applies them to the running configuration via fleet_config.

This is the MISSING PIECE that PIPELINE_AUTO_TUNE_IMPLEMENTATION.md identified:
    "decisions are NOT YET APPLIED by the runner."

meta_loop.py's _plan_auto_tune_decisions() generates decisions:
  - Gate bypass when first_try_yield < 60%
  - Model rotation when cycle_time regresses > 15%
  - Batch sizing adjustments

Those decisions are written to resource_events(kind='auto_tune_decision')
but nothing reads them.  This module closes the loop.

Guardrails (from PIPELINE_AUTO_TUNE_IMPLEMENTATION.md):
  - ORCH_TUNE_MIN_SAMPLES  = 50  (don't act on thin data)
  - ORCH_TUNE_MAX_CHANGE_PCT = 15 (no huge swings)
  - One change per run (MAX_APPLY_PER_RUN)
  - Cooldown period between applications

Loop type: 'auto_tune_apply' (cadence 3600s — hourly).
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_APPLY_PER_RUN = int(os.environ.get("TUNE_MAX_APPLY_PER_RUN", "1"))
COOLDOWN_S = int(os.environ.get("TUNE_COOLDOWN_S", str(24 * 3600)))   # 24h default
RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".runtime")


def _last_applied_ts():
    """When was the last decision applied?  Return epoch float or 0."""
    path = os.path.join(RUNTIME_DIR, "auto_tune_last_applied.json")
    try:
        with open(path) as f:
            return float(json.load(f).get("ts", 0))
    except Exception:
        return 0.0


def _record_applied():
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        with open(os.path.join(RUNTIME_DIR, "auto_tune_last_applied.json"), "w") as f:
            json.dump({"ts": time.time()}, f)
    except Exception:
        pass


def _set_fleet_config(key, value):
    """Write to fleet_config table (all runners read this on each loop)."""
    try:
        db.upsert("fleet_config", {
            "key": key,
            "value": str(value),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        print(f"[auto_tune_applicator] fleet_config: {key} = {value}")
    except Exception as e:
        print(f"[auto_tune_applicator] fleet_config write failed for {key}: {e}")


def apply_pending_decisions():
    """Read active auto-tune decisions and apply via fleet_config.
    Returns the number of decisions applied."""
    # Cooldown guard
    if time.time() - _last_applied_ts() < COOLDOWN_S:
        print("[auto_tune_applicator] cooldown active — skipping")
        return 0

    try:
        decisions = db.select("resource_events", {
            "select": "id,detail",
            "kind": "eq.auto_tune_decision",
            "order": "created_at.desc",
            "limit": "50",
        }) or []
    except Exception as e:
        print(f"[auto_tune_applicator] failed to read decisions: {e}")
        return 0

    applied = 0
    for event in decisions:
        if applied >= MAX_APPLY_PER_RUN:
            break
        try:
            detail = event.get("detail")
            if isinstance(detail, str):
                detail = json.loads(detail)
            if not isinstance(detail, dict):
                continue
            # Skip already-applied or inactive decisions
            if detail.get("applied") or detail.get("status") == "rolled_back":
                continue
            if detail.get("status") not in (None, "active", "pending"):
                continue

            action = detail.get("action", "")

            if action == "bypass_build_gate_for_low_risk":
                pct = min(int(detail.get("pct_change", 10)), 15)   # cap at MAX_CHANGE_PCT
                _set_fleet_config("ORCH_SOFT_GATE_BYPASS_PCT", pct)

            elif action == "rotate_to_cheaper_models":
                _set_fleet_config("ORCH_MODEL_TIER_OVERRIDE", "cost_optimize")

            elif action == "increase_batch_size":
                size = min(int(detail.get("batch_size", 5)), 10)   # sane ceiling
                _set_fleet_config("ORCH_BATCH_SIZE", size)

            elif action == "tighten_cycle_time":
                target = max(int(detail.get("target_seconds", 14400)), 3600)  # floor 1h
                _set_fleet_config("ORCH_CYCLE_TIME_TARGET_S", target)

            else:
                # Unknown action — log but don't crash
                print(f"[auto_tune_applicator] unknown action: {action}")
                continue

            # Mark decision as applied
            detail["applied"] = True
            detail["applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            db.update("resource_events", {"id": event["id"]},
                      {"detail": json.dumps(detail)})
            applied += 1

        except Exception as e:
            print(f"[auto_tune_applicator] failed to apply decision {event.get('id')}: {e}")

    if applied:
        _record_applied()
    print(f"[auto_tune_applicator] applied {applied} decisions")
    return applied


def rollback_decision(event_id, reason="manual rollback"):
    """Rollback a specific decision by event id."""
    try:
        rows = db.select("resource_events", {
            "select": "id,detail",
            "id": f"eq.{event_id}",
        }) or []
        if not rows:
            print(f"[auto_tune_applicator] decision {event_id} not found")
            return False
        detail = rows[0].get("detail")
        if isinstance(detail, str):
            detail = json.loads(detail)
        detail["status"] = "rolled_back"
        detail["rollback_reason"] = reason
        detail["rolled_back_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        db.update("resource_events", {"id": event_id}, {"detail": json.dumps(detail)})
        print(f"[auto_tune_applicator] rolled back decision {event_id}: {reason}")
        return True
    except Exception as e:
        print(f"[auto_tune_applicator] rollback failed for {event_id}: {e}")
        return False


def run():
    """Entry point called by loops.py for the 'auto_tune_apply' loop type."""
    return apply_pending_decisions()


if __name__ == "__main__":
    n = run()
    print(f"Applied {n} auto-tune decisions")
