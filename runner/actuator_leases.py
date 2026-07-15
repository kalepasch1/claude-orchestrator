#!/usr/bin/env python3
"""Cross-runner event-sourced leases for periodic actuators."""
from __future__ import annotations
import json, os, socket, threading, time, uuid
import db

_local = {}; _lock = threading.Lock()

def owner(): return os.environ.get("RUNNER_ID") or f"{socket.gethostname()}-{os.getpid()}"

def acquire(actuator: str, ttl: int = 300, lease_owner: str = "") -> dict:
    lease_owner = lease_owner or owner()
    try:
        rows = db.rpc("acquire_actuator_lease", {"p_actuator": actuator, "p_owner": lease_owner,
                      "p_ttl_seconds": max(15, int(ttl))}) or []
        row = rows[0] if rows else {}
        return {"acquired": bool(row.get("acquired")), "token": row.get("lease_token"),
                "until": row.get("lease_until"), "source": "database"}
    except Exception:
        now=time.time()
        with _lock:
            current=_local.get(actuator)
            if current and current[1] > now and current[0] != lease_owner:
                return {"acquired":False,"source":"local-fallback"}
            token=str(uuid.uuid4()); _local[actuator]=(lease_owner,now+ttl,token)
            return {"acquired":True,"token":token,"until":now+ttl,"source":"local-fallback"}

def event(actuator: str, event_name: str, success=None, token=None, **detail):
    row={"actuator":actuator,"owner":owner(),"lease_token":token,"event":event_name,
         "success":success,"detail":detail}
    try: db.insert("actuator_events",row)
    except Exception: pass
    return row
