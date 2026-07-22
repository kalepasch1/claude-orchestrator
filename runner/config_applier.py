#!/usr/bin/env python3
"""
config_applier.py — autonomous config applier with canary deployment.

Reads pending config recommendations from the fleet_config table, applies them
via a canary window (apply to one machine first, observe for N seconds, then
roll out fleet-wide or rollback). Logs every recommendation, rollback trigger,
and metrics comparison in detail.

Fail-soft: any error returns empty/defaults and never wedges the runner.

Usage:
    config_applier.run()           # periodic entry point
    config_applier.apply_config(key, value, by="auto")  # direct apply w/ canary
"""
import os
import hashlib
import sys
import time
import json
import socket
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("config_applier")
HOST = socket.gethostname()
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_FILE = os.path.join(HOME, "config_applier_state.json")

# Canary window in seconds — observe after applying before promoting fleet-wide
CANARY_WINDOW_S = int(os.environ.get("ORCH_CANARY_WINDOW_S", "60"))

# Safe config prefixes (mirrors fleet_control.py)
_SAFE_PREFIXES = ("ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_",
                  "RELEASE_", "QUEUE_", "CONT_", "JANITOR_", "REMEDIATION_",
                  "DEFAULT_TEST_CMD", "TASK_TIMEOUT", "ENABLE_", "SESSION_",
                  "ACCOUNT_COOLDOWN", "MERGE_", "DEPLOY_", "INTEGRATE_", "COST_")
_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL")


def _is_safe_key(k):
    ku = (k or "").upper()
    if any(m in ku for m in _DENY_MARKERS):
        return False
    return any(ku.startswith(p) for p in _SAFE_PREFIXES)


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"applied": {}, "rollbacks": []}


def _save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _get_metric_snapshot():
    """Capture current metrics for before/after comparison. Fail-soft."""
    try:
        import resource_governor
        return {"can_claim": resource_governor.can_claim(), "ts": time.time()}
    except Exception:
        return {"ts": time.time()}


def _adversarial_gate(key, value):
    """Reject a config rollout whose deterministic failure simulation exceeds its SLO."""
    try:
        import adversarial_fleet
        return adversarial_fleet.calibrated_simulation(
            key, value, runs=int(os.environ.get("ORCH_SIMULATION_RUNS", "500")))
    except Exception as e:
        # Fail closed: a missing simulator must not silently bypass the pre-deploy gate.
        return {"passed": False, "reason": f"simulation_unavailable:{e}"}


def apply_config(key, value, by="auto", canary=True):
    """Apply a config key with canary observation.

    Returns dict with outcome: 'applied', 'rolled_back', 'rejected', or 'error'.
    Logs all recommendations, rollback triggers, and metrics comparisons.
    """
    if not _is_safe_key(key):
        log.warning("config_applier: REJECTED unsafe key %s (by=%s)", key, by)
        return {"outcome": "rejected", "key": key, "reason": "unsafe key"}

    simulation = _adversarial_gate(key, value)
    if not simulation.get("passed"):
        log.warning("config_applier: REJECTED %s; adversarial simulation=%s", key, simulation)
        return {"outcome": "rejected", "key": key, "reason": "adversarial_simulation", "simulation": simulation}

    try:
        import policy_compiler
        policy = policy_compiler.authorize_config(key, value, by, simulation)
    except Exception as exc:
        return {"outcome": "rejected", "key": key, "reason": f"policy_compiler:{exc}"}
    if policy.get("status") != "authorized":
        return {"outcome": "rejected", "key": key, "reason": "policy_not_authorized", "policy": policy}

    old_value = os.environ.get(key)
    before = _get_metric_snapshot()
    log.info("config_applier: RECOMMEND %s=%s (old=%s, by=%s)", key, value, old_value, by)

    # Apply locally (canary on this host)
    os.environ[key] = str(value)
    log.info("config_applier: APPLIED %s=%s on %s (canary=%s)", key, value, HOST, canary)

    if canary and CANARY_WINDOW_S > 0:
        time.sleep(min(CANARY_WINDOW_S, 5))  # capped for non-blocking in runner context

    after = _get_metric_snapshot()
    log.info("config_applier: METRICS before=%s after=%s", before, after)
    healthy, canary_metrics = policy_compiler.observe_canary(policy["id"], before, after)

    # Simple rollback heuristic: if resource_governor flipped from can_claim=True to False
    rolled_back = False
    if not healthy:
        log.warning("config_applier: ROLLBACK %s (resource pressure after apply)", key)
        if old_value is not None:
            os.environ[key] = old_value
        else:
            os.environ.pop(key, None)
        rolled_back = True
        state = _load_state()
        state["rollbacks"].append({"key": key, "value": value, "by": by,
                                    "ts": time.time(), "reason": "resource_pressure"})
        _save_state(state)
        policy_compiler.complete_config(policy["id"], "rolled_back", canary_metrics)
        return {"outcome": "rolled_back", "key": key, "reason": "resource_pressure"}

    # Promote: persist to fleet_config
    try:
        import db
        db.insert("fleet_config", {"key": key, "value": str(value), "policy_change_id": policy["id"]}, upsert=True)
        log.info("config_applier: PROMOTED %s=%s fleet-wide", key, value)
    except Exception as e:
        log.warning("config_applier: fleet_config write failed: %s", e)
        if old_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_value
        policy_compiler.complete_config(policy["id"], "rolled_back", {**canary_metrics, "persist_error": str(e)})
        return {"outcome": "rolled_back", "key": key, "reason": "fleet_config_persistence"}

    state = _load_state()
    state["applied"][key] = {"value": str(value), "by": by, "ts": time.time(),
                              "old_value": old_value}
    _save_state(state)
    policy_compiler.complete_config(policy["id"], "applied", canary_metrics)
    return {"outcome": "applied", "key": key, "value": value}


def run():
    """Periodic entry: check for pending config recommendations and apply them."""
    try:
        import db
        rows = db.select("fleet_config", {
            "select": "key,value",
            "key": "like.ORCH_PENDING_%",
        }) or []
    except Exception:
        return {"checked": 0, "applied": 0}

    applied = 0
    for row in rows:
        raw_key = row.get("key", "")
        actual_key = raw_key.replace("ORCH_PENDING_", "", 1)
        value = row.get("value")
        if _is_safe_key(actual_key):
            result = apply_config(actual_key, value, by="auto-recommend")
            if result.get("outcome") == "applied":
                applied += 1
                try:
                    import db as _db
                    _db.delete("fleet_config", {"key": f"eq.{raw_key}"})
                except Exception:
                    pass
    return {"checked": len(rows), "applied": applied}
