#!/usr/bin/env python3
"""fleet_capabilities.py — publish and query which local (Ollama) models each live
machine actually has pulled, and how much local capacity each one has free right now.

Two Macs pulling from the same Supabase queue already can't double-claim a task —
db.claim_task() ends every claim with an atomic optimistic PATCH. But that's task-level
coordination only. Nothing previously published *which locally pulled models* each box
has or how many local lanes are free, so the fleet had no way to know "Mac 2 has
qwen3-coder:30b hot and a free lane, Mac 1 doesn't have it pulled at all" — a task
wanting that model locally was a coin flip between a fast free local run and a silent
fallback to a paid cloud model, purely based on which runner happened to poll first.

This closes that gap using the same `controls` key/value table lane_scheduler.py already
writes to (no schema migration, no new table). Each machine's snapshot is a JSON blob at
key f"ollama_capabilities_{hostname}"; readers treat anything older than
ORCH_FLEET_CAPABILITY_TTL_S as stale and ignore it (mirrors fleet.py's heartbeat TTL
pattern), so a machine that goes to sleep or crashes ages out instead of being routed to
forever.
"""
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_KEY_PREFIX = "ollama_capabilities_"
_TTL_S = int(os.environ.get("ORCH_FLEET_CAPABILITY_TTL_S", "180"))


def _db():
    import db
    return db


def snapshot(hostname=None, running_models=None):
    """Build (without publishing) this machine's capability payload. Split out from
    publish() so tests/callers can inspect it without a DB round-trip."""
    try:
        import machine_profile
    except Exception:
        return None
    host = hostname or socket.gethostname()
    prof = machine_profile.profile(host)
    try:
        import ollama_catalog
        candidates = ollama_catalog.candidates()
    except Exception:
        candidates = []
    return {
        "hostname": host,
        "max_ollama_lanes": prof["max_ollama_lanes"],
        "max_ollama_gb": prof["max_ollama_gb"],
        "free_ram_gb": prof.get("free_ram_gb"),
        "heavy_models": prof["heavy_models"],
        "available_models": [{"model": c["model"], "cap": c["cap"]} for c in candidates],
        "running_models": list(running_models or []),
        "updated_at": time.time(),
    }


def publish(hostname=None, running_models=None):
    """Upsert this machine's capability snapshot. Fail-soft: call this from any periodic
    loop (lane_scheduler.run() does) without worrying about DB/network errors."""
    payload = snapshot(hostname=hostname, running_models=running_models)
    if not payload:
        return False
    try:
        _db().insert("controls",
                     {"key": f"{_KEY_PREFIX}{payload['hostname']}", "value": json.dumps(payload),
                      "updated_at": "now()"},
                     upsert=True)
        return True
    except Exception:
        return False


def _fresh(payload, now=None):
    try:
        now = time.time() if now is None else now
        return (now - float(payload.get("updated_at", 0))) <= _TTL_S
    except Exception:
        return False


def all_capabilities(rows=None):
    """{hostname: payload} for every machine with a fresh capability snapshot.

    `rows` is exposed for tests; normally read live from the `controls` table."""
    out = {}
    if rows is None:
        try:
            rows = _db().select("controls", {"select": "key,value",
                                              "key": f"like.{_KEY_PREFIX}*"}) or []
        except Exception:
            return out
    for row in rows:
        try:
            payload = json.loads(row.get("value") or "{}")
        except Exception:
            continue
        if _fresh(payload):
            out[payload.get("hostname") or row.get("key")] = payload
    return out


def machines_with_model(model, rows=None):
    """Live machines that currently have `model` pulled, best free-capacity first."""
    caps = all_capabilities(rows=rows)
    out = []
    for host, payload in caps.items():
        names = {m.get("model") for m in payload.get("available_models", [])}
        if model not in names:
            continue
        free_lanes = payload.get("max_ollama_lanes", 0) - len(payload.get("running_models", []))
        out.append({"hostname": host, "free_lanes": free_lanes,
                    "free_ram_gb": payload.get("free_ram_gb") or 0})
    out.sort(key=lambda m: (-m["free_lanes"], -(m["free_ram_gb"] or 0)))
    return out


def best_machine_for(model, rows=None):
    """Hostname of the best live machine to run `model` on locally, or None if no live
    machine currently has it pulled."""
    hosts = machines_with_model(model, rows=rows)
    return hosts[0]["hostname"] if hosts else None


def this_machine_has(model):
    try:
        import ollama_catalog
        return any(c["model"] == model for c in ollama_catalog.candidates())
    except Exception:
        return False


def should_claim_locally(model, hostname=None):
    """Should THIS machine claim/serve a task that wants `model` locally? True if this
    box already has it; if not, and a live peer does, prefer that peer (fail open — if
    fleet state is unreadable, don't block work, just don't claim a false positive)."""
    if this_machine_has(model):
        return True
    host = hostname or socket.gethostname()
    hosts = machines_with_model(model)
    if not hosts:
        return False  # nobody has it locally — caller should fall back to cloud/API
    return hosts[0]["hostname"] == host


if __name__ == "__main__":
    print(json.dumps(all_capabilities(), indent=2, default=str))
