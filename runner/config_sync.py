#!/usr/bin/env python3
"""
config_sync.py — automated configuration synchronization across the fleet.

Replaces manual config pushes from local environments to production.
Watches for local config file changes, validates them, and syncs to the
fleet_config table so all machines converge automatically via fleet_control.

Sync flow:
  1. Read local config overrides from ~/.claude-orchestrator/config.local.json
  2. Diff against current fleet_config values
  3. Apply changed keys through config_applier (with canary)
  4. Record sync events for audit

Fail-soft: errors are logged, never raised.
"""
import os
import sys
import json
import time
import logging
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("config_sync")

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LOCAL_CONFIG = os.path.join(HOME, "config.local.json")
SYNC_STATE_FILE = os.path.join(HOME, "config_sync_state.json")
ENABLED = os.environ.get("ORCH_CONFIG_SYNC", "true").lower() == "true"
SYNC_INTERVAL_S = int(os.environ.get("ORCH_CONFIG_SYNC_INTERVAL_S", "300"))

_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL")
_SAFE_PREFIXES = ("ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_",
                  "RELEASE_", "QUEUE_", "CONT_", "JANITOR_", "REMEDIATION_",
                  "DEFAULT_TEST_CMD", "TASK_TIMEOUT", "ENABLE_", "SESSION_",
                  "ACCOUNT_COOLDOWN", "MERGE_", "DEPLOY_", "INTEGRATE_", "COST_")

_lock = threading.Lock()
_stats = {"syncs": 0, "keys_pushed": 0, "keys_skipped": 0, "errors": 0}


def stats():
    return dict(_stats)


def _is_safe_key(k):
    ku = (k or "").upper()
    if any(m in ku for m in _DENY_MARKERS):
        return False
    return any(ku.startswith(p) for p in _SAFE_PREFIXES)


def _load_local_config():
    """Load local config overrides. Returns dict or empty."""
    try:
        with open(LOCAL_CONFIG) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.debug("failed to read local config: %s", e)
        return {}


def _load_sync_state():
    try:
        with open(SYNC_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"last_sync": 0, "synced_keys": {}}


def _save_sync_state(state):
    try:
        os.makedirs(os.path.dirname(SYNC_STATE_FILE), exist_ok=True)
        with open(SYNC_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _get_fleet_config():
    """Fetch current fleet_config from DB. Returns dict of key->value."""
    try:
        import db
        rows = db.select("fleet_config", {"select": "key,value"}) or []
        return {r["key"]: r["value"] for r in rows if r.get("key")}
    except Exception:
        return {}


def compute_diff(local, remote):
    """Compute config keys that differ between local and remote.

    Returns list of {'key': str, 'local_value': str, 'remote_value': str|None, 'action': 'set'|'delete'}
    """
    changes = []
    for k, v in local.items():
        if not _is_safe_key(k):
            continue
        remote_val = remote.get(k)
        if remote_val != str(v):
            changes.append({
                "key": k,
                "local_value": str(v),
                "remote_value": remote_val,
                "action": "set",
            })
    return changes


def sync_config(dry_run=False):
    """Synchronize local config overrides to fleet_config.

    Returns dict with 'applied': int, 'skipped': int, 'changes': list
    """
    if not ENABLED:
        return {"applied": 0, "skipped": 0, "changes": [], "reason": "sync disabled"}

    local = _load_local_config()
    if not local:
        return {"applied": 0, "skipped": 0, "changes": [], "reason": "no local config"}

    remote = _get_fleet_config()
    changes = compute_diff(local, remote)

    if not changes:
        return {"applied": 0, "skipped": 0, "changes": [], "reason": "no changes"}

    applied = 0
    skipped = 0

    if not dry_run:
        try:
            import config_applier
            for change in changes:
                key = change["key"]
                value = change["local_value"]
                try:
                    result = config_applier.apply_config(key, value, by="config_sync")
                    if result and result.get("outcome") in ("applied", None):
                        applied += 1
                    else:
                        skipped += 1
                except Exception as e:
                    log.debug("failed to apply %s: %s", key, e)
                    skipped += 1
        except ImportError:
            # Fall back to direct DB upsert if config_applier unavailable
            try:
                import db
                for change in changes:
                    try:
                        db.upsert("fleet_config", {"key": change["key"], "value": change["local_value"]})
                        applied += 1
                    except Exception:
                        skipped += 1
            except Exception:
                skipped = len(changes)
    else:
        skipped = len(changes)

    with _lock:
        _stats["syncs"] += 1
        _stats["keys_pushed"] += applied
        _stats["keys_skipped"] += skipped

    state = _load_sync_state()
    state["last_sync"] = time.time()
    for c in changes:
        if not dry_run:
            state["synced_keys"][c["key"]] = c["local_value"]
    _save_sync_state(state)

    return {"applied": applied, "skipped": skipped, "changes": changes}


def run():
    """Periodic entry point — sync if enough time has passed."""
    if not ENABLED:
        return
    state = _load_sync_state()
    elapsed = time.time() - state.get("last_sync", 0)
    if elapsed < SYNC_INTERVAL_S:
        return
    try:
        result = sync_config()
        if result.get("applied", 0) > 0:
            log.info("config_sync: applied %d keys", result["applied"])
    except Exception as e:
        with _lock:
            _stats["errors"] += 1
        log.warning("config_sync error: %s", e)
