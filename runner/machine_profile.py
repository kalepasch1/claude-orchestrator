#!/usr/bin/env python3
"""machine_profile.py — single source of truth for what THIS machine can handle locally.

Replaces the old lane_scheduler.py MACHINE_PROFILES dict, which was a hardcoded
{"Mac.lan": {...}, "Mandys-MacBook-Pro.local": {...}} keyed by exact socket.gethostname()
string. That has two failure modes that were both live on this fleet:

  1. Any hostname that doesn't match one of the hardcoded keys byte-for-byte (a renamed
     Mac, a new Mac 3, a Tailscale/mDNS name that differs from the Sharing-panel computer
     name) silently falls back to a generic 2-lane/16GB profile — no error, no signal,
     just quietly wrong capacity.
  2. The "heavy_models" / exclusive-model list was a hand-maintained string list, kept in
     THREE different places (MACHINE_PROFILES here, ORCH_EXCLUSIVE_OLLAMA_MODELS in
     runner/.env, and the model catalog in ollama_install_planner.py) that drift out of
     sync the moment a model is pulled, renamed, or removed on one box and not the others.

This module computes everything from the machine's actual live state instead:
total/free RAM (resource_governor, already macOS-accurate), and which models are
*currently installed* (ollama_catalog). "Heavy" is relative to THIS box's own budget, so
a 22B model is exclusive on a 16GB Mac and shareable on a 64GB Mac without editing any
config anywhere. Works for any number of machines with zero code changes.

Explicit control still works two ways, both additive rather than replacing the computed
values (so a stale central config value can't silently blank out a machine's real
capacity — see _fold_env_exclusive):
  - ORCH_MACHINE_PROFILE_OVERRIDES_JSON: {"hostname": {"max_ollama_lanes": N, ...}} —
    full-field override for a specific host, for when an operator wants to hand-tune one
    box (e.g. reserve headroom for something outside the orchestrator's view).
  - ORCH_EXCLUSIVE_OLLAMA_MODELS: comma list folded in as EXTRA forced-exclusive names.
"""
import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _resource_governor():
    try:
        import resource_governor
        return resource_governor
    except Exception:
        return None


def total_ram_gb():
    """Total system RAM in GB, or None if it can't be determined."""
    rg = _resource_governor()
    if rg:
        try:
            v = rg.total_gb()
            if v:
                return float(v)
        except Exception:
            pass
    try:
        import subprocess
        raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5).strip()
        return round(int(raw) / 1e9, 1)
    except Exception:
        return None


def free_ram_gb():
    """Free/available system RAM in GB right now, or None if unavailable."""
    rg = _resource_governor()
    if rg:
        try:
            return rg.ram_free_gb()
        except Exception:
            pass
    return None


def _local_model_ram_gb(model):
    try:
        import local_model_slots
        return local_model_slots.ram_gb(model)
    except Exception:
        return 6.0


def _floor_gb():
    """RAM floor to reserve, delegating to resource_governor.effective_floor_gb() so this
    stays in lockstep with the same floor the rest of the fleet enforces (RAM_FLOOR_GB,
    default 2.0) instead of hardcoding a second, possibly-stale default here."""
    rg = _resource_governor()
    if rg:
        try:
            return float(rg.effective_floor_gb())
        except Exception:
            pass
    return float(os.environ.get("RAM_FLOOR_GB", "2.0"))


def installed_models():
    """Models currently pulled/visible on this box (production + canary-gated)."""
    try:
        import ollama_catalog
        return [c["model"] for c in ollama_catalog.candidates(include_canary_only=True)]
    except Exception:
        return []


def _overrides():
    raw = os.environ.get("ORCH_MACHINE_PROFILE_OVERRIDES_JSON", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _fold_env_exclusive(heavy):
    """Add any names from ORCH_EXCLUSIVE_OLLAMA_MODELS as EXTRA forced-exclusive entries.

    Deliberately additive, never a replacement: this env var (or a stale central
    fleet_config row of the same name pushed from Mac 1) used to be the ONLY source of
    truth, hardcoded to one machine's numbers and copy-pasted verbatim onto every other
    machine per SETUP-MAC2.md. Treating it as additive means an old/wrong value can only
    ever make this box more conservative, never silently erase its real, computed
    capacity."""
    extra = [x.strip() for x in os.environ.get("ORCH_EXCLUSIVE_OLLAMA_MODELS", "").split(",") if x.strip()]
    out = list(heavy)
    for m in extra:
        if m not in out:
            out.append(m)
    return out


def profile(hostname=None):
    """Compute this machine's live Ollama capacity profile.

    max_ollama_gb    - RAM this box may give Ollama, reserving the same RAM floor
                        resource_governor.effective_floor_gb() uses fleet-wide (RAM_FLOOR_GB,
                        default 2.0) plus a share for everything else the runner is doing
                        concurrently.
    max_ollama_lanes - how many local models this box can run loaded at once.
    heavy_models     - which of the CURRENTLY INSTALLED local models need exclusive
                        access on THIS box (too big to share a lane), derived from each
                        model's real RAM need vs. this box's own budget — not a hardcoded
                        list.
    """
    host = hostname or socket.gethostname()
    total = total_ram_gb()
    share = float(os.environ.get("ORCH_OLLAMA_RAM_SHARE", "0.6"))
    floor = _floor_gb()
    lane_cost_gb = float(os.environ.get("ORCH_OLLAMA_LANE_COST_GB", "7.0"))
    exclusive_fraction = float(os.environ.get("ORCH_OLLAMA_EXCLUSIVE_FRACTION", "0.75"))

    if total:
        max_ollama_gb = max(0.0, round(total * share - floor, 1))
    else:
        # Can't read real specs (e.g. no sysctl/resource_governor available) — stay
        # conservative rather than guessing generous defaults.
        max_ollama_gb = float(os.environ.get("ORCH_OLLAMA_FALLBACK_GB", "8"))

    max_ollama_lanes = max(1, int(max_ollama_gb // lane_cost_gb)) if max_ollama_gb > 0 else 1

    models = installed_models()
    heavy = [m for m in models
             if max_ollama_gb <= 0 or _local_model_ram_gb(m) >= max_ollama_gb * exclusive_fraction]
    heavy = _fold_env_exclusive(heavy)

    result = {
        "hostname": host,
        "total_ram_gb": total,
        "free_ram_gb": free_ram_gb(),
        "max_ollama_gb": max_ollama_gb,
        "max_ollama_lanes": max_ollama_lanes,
        "heavy_models": heavy,
        "installed_models": models,
        "source": "dynamic",
    }

    ov = _overrides().get(host)
    if isinstance(ov, dict):
        result.update(ov)
        result["source"] = "override"
    return result


if __name__ == "__main__":
    print(json.dumps(profile(), indent=2))
