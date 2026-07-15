#!/usr/bin/env python3
"""config_drift.py - Detect configuration drift across fleet nodes."""
import os, sys, hashlib, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
def _config_hash():
    try:
        rows = db.select("fleet_config", {"select": "key,value", "order": "key.asc"}) or []
    except Exception:
        rows = []
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()[:16]
def _executor_hashes():
    try:
        return db.select("fleet_config", {"select": "key,value", "key": "like.COWORK_EXECUTOR_%_LAST_RUN"}) or []
    except Exception:
        return []
def check():
    expected = _config_hash()
    drifted = []
    for hb in _executor_hashes():
        try:
            val = json.loads(hb["value"]) if isinstance(hb["value"], str) else hb["value"]
            rh = val.get("config_hash", "")
            if rh and rh != expected: drifted.append({"executor": hb["key"], "expected": expected, "reported": rh})
        except (json.JSONDecodeError, TypeError): pass
    print(f"config_drift: {len(drifted)} executor(s) drifted" if drifted else "config_drift: in sync")
    return drifted
if __name__ == "__main__": check()
