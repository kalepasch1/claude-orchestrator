#!/usr/bin/env python3
"""fleet_sync_check.py — run on EITHER Mac to answer "are the two boxes in sync and
seeing each other correctly?" in one shot.

Prints:
  - this machine's git commit (so you can spot a Mac that missed a `git pull`)
  - this machine's live capacity profile (machine_profile.py) and locally pulled models
  - every live machine's published capability snapshot (fleet_capabilities.py) — if this
    section only shows ONE host while you have two Macs running, that Mac's lane_scheduler
    loop either isn't running or can't reach Supabase
  - fleet.py's heartbeat-based liveness view, for cross-check against the above
  - a plain-language diff: models present on one live Mac but not the other

Usage:  python3 fleet_sync_check.py [--json]
"""
import json
import os
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _git_commit():
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                      cwd=os.path.dirname(os.path.abspath(__file__)),
                                      text=True, timeout=10).strip()
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                         cwd=os.path.dirname(os.path.abspath(__file__)),
                                         text=True, timeout=10).strip()
        porcelain = subprocess.check_output(["git", "status", "--porcelain"],
                                            cwd=os.path.dirname(os.path.abspath(__file__)),
                                            text=True, timeout=10)
        # Untracked files (??) are not "dirty" — counting them made intake/processed/*.md
        # droppings raise a permanent false DIRTY flag (2026-07-31 incident).
        tracked_changes = [l for l in porcelain.splitlines()
                           if l.strip() and not l.startswith("??")]
        untracked = [l for l in porcelain.splitlines() if l.startswith("??")]
        return {"commit": out, "branch": branch, "dirty": bool(tracked_changes),
                "untracked_count": len(untracked)}
    except Exception as e:
        return {"error": str(e)}


def _this_machine():
    try:
        import machine_profile
        prof = machine_profile.profile()
    except Exception as e:
        prof = {"error": str(e)}
    return {"hostname": socket.gethostname(), "profile": prof, "git": _git_commit()}


def _fleet_capabilities():
    try:
        import fleet_capabilities
        return fleet_capabilities.all_capabilities()
    except Exception as e:
        return {"error": str(e)}


def _fleet_status():
    try:
        import fleet
        return fleet.status()
    except Exception as e:
        return {"error": str(e)}


def _model_diff(caps):
    """Models present on some live machine(s) but not all — the thing that makes fleet
    task routing silently fall back to cloud instead of running locally for free."""
    if not isinstance(caps, dict) or len(caps) < 2:
        return {"note": "need 2+ live machines with fresh capability snapshots to diff"}
    by_host = {h: {m["model"] for m in payload.get("available_models", [])}
               for h, payload in caps.items()}
    all_models = set().union(*by_host.values()) if by_host else set()
    missing = {}
    for host, have in by_host.items():
        gap = sorted(all_models - have)
        if gap:
            missing[host] = gap
    return missing or {"note": "model inventories match across all live machines"}


def run():
    this = _this_machine()
    caps = _fleet_capabilities()
    fstatus = _fleet_status()
    diff = _model_diff(caps)
    return {
        "this_machine": this,
        "live_fleet_heartbeats": fstatus,
        "live_fleet_capabilities": caps,
        "model_inventory_gaps": diff,
    }


if __name__ == "__main__":
    result = run()
    if "--json" in sys.argv:
        print(json.dumps(result, indent=2, default=str))
    else:
        this = result["this_machine"]
        print(f"== this machine: {this['hostname']} ==")
        git = this.get("git", {})
        if "error" in git:
            print(f"  git: unreadable ({git['error']})")
        else:
            print(f"  git: {git['branch']}@{git['commit']}" + (" (DIRTY — uncommitted changes)" if git.get("dirty") else ""))
        prof = this.get("profile", {})
        if "error" in prof:
            print(f"  profile: unreadable ({prof['error']})")
        else:
            print(f"  profile: {prof.get('source')} — {prof.get('max_ollama_lanes')} lanes, "
                  f"{prof.get('max_ollama_gb')}GB budget, {prof.get('total_ram_gb')}GB total RAM")
            print(f"  installed models: {', '.join(prof.get('installed_models') or []) or '(none)'}")
            print(f"  heavy/exclusive here: {', '.join(prof.get('heavy_models') or []) or '(none)'}")

        fstatus = result["live_fleet_heartbeats"]
        print()
        if isinstance(fstatus, dict) and "machines_live" in fstatus:
            print(f"== fleet heartbeats: {fstatus['machines_live']} live machine(s) ==")
            for m in fstatus.get("machines", []):
                print(f"  {m.get('host')}: {m.get('active')} active tasks, last_seen={m.get('last_seen')}")
        else:
            print(f"== fleet heartbeats: unreadable ({fstatus.get('error') if isinstance(fstatus, dict) else fstatus}) ==")

        caps = result["live_fleet_capabilities"]
        print()
        if isinstance(caps, dict) and "error" not in caps:
            print(f"== fleet local-model capabilities: {len(caps)} live machine(s) publishing ==")
            for host, payload in caps.items():
                free = payload.get("max_ollama_lanes", 0) - len(payload.get("running_models", []))
                models = [m["model"] for m in payload.get("available_models", [])]
                print(f"  {host}: {free} free lane(s), models: {', '.join(models) or '(none)'}")
        else:
            print(f"== fleet local-model capabilities: unreadable ({caps.get('error') if isinstance(caps, dict) else caps}) ==")
            print("  (this is expected until both Macs are running the updated lane_scheduler.py)")

        diff = result["model_inventory_gaps"]
        print()
        if "note" in diff:
            print(f"== model inventory: {diff['note']} ==")
        else:
            print("== model inventory gaps (present on one live Mac, missing on another) ==")
            for host, missing in diff.items():
                print(f"  {host} is missing: {', '.join(missing)}")
