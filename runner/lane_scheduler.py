"""
lane_scheduler.py — local model lane scheduler.

Mac-aware scheduling for Ollama and other local models:
1. Smaller-RAM Macs carry fewer local model lanes; bigger-RAM Macs carry more.
2. Heavy Ollama models run one-at-a-time with guaranteed unload.
3. Orphan process cleanup prevents RAM thrash.
4. Every run() publishes this machine's local-model capability snapshot so the rest of
   the fleet (dashboard, other runners) can see which models are actually pulled here.

Protects throughput from RAM thrash by treating local model capacity as a managed
resource.

Machine capacity used to be a hardcoded MACHINE_PROFILES dict keyed by exact
socket.gethostname() string ("Mac.lan", "Mandys-MacBook-Pro.local"). Any hostname that
didn't match byte-for-byte silently fell back to a generic 2-lane/16GB profile, and the
"heavy"/exclusive model list was a hand-maintained string duplicated across this file,
runner/.env, and ollama_install_planner.py — the three drifted the moment a model was
pulled/removed on one box and not the others. That's now computed live per-machine by
machine_profile.py (see that module's docstring for the full rationale) — this file just
consumes it.
"""
import os, sys, subprocess, json, socket, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HEAVY_MODEL_GB = float(os.environ.get("ORCH_HEAVY_MODEL_GB", "8"))


def _profile(hostname=None):
    try:
        import machine_profile
        return machine_profile.profile(hostname)
    except Exception:
        # Fail-soft floor if machine_profile itself can't be imported/computed — matches
        # the old generic fallback so a broken import degrades gracefully, not silently.
        return {"hostname": hostname or socket.gethostname(), "max_ollama_lanes": 2,
                "max_ollama_gb": 16, "heavy_models": [], "total_ram_gb": None, "free_ram_gb": None}


def run():
    """Periodic entry: manage local model lanes, cleanup orphans, publish fleet capability."""
    hostname = socket.gethostname()
    profile = _profile(hostname)

    # 1. Check current Ollama state
    running = _ollama_running_models()
    running_names = [m.get("name", "") for m in running]

    # 2. Kill orphan processes
    orphans_killed = _kill_orphans(profile)

    # 3. Unload idle models to free RAM
    unloaded = _unload_idle_models(running, profile)

    # 4. Check RAM pressure — reuse resource_governor's macOS-accurate accounting
    # (reclaimable-cache-aware) instead of a second hand-rolled vm_stat parser.
    ram_ok = _check_ram_pressure()

    # 5. Report lane availability
    available_lanes = profile["max_ollama_lanes"] - len(running)

    # 6. Publish this machine's capability snapshot so the rest of the fleet knows what's
    # actually available here (models pulled + free lanes), not just that a heartbeat exists.
    try:
        import fleet_capabilities
        fleet_capabilities.publish(hostname=hostname, running_models=running_names)
    except Exception:
        pass

    try:
        db.insert("controls", {
            "key": f"lane_scheduler_{hostname}",
            "value": json.dumps({
                "hostname": hostname,
                "max_ollama_lanes": profile["max_ollama_lanes"],
                "max_ollama_gb": profile.get("max_ollama_gb"),
                "profile_source": profile.get("source"),
                "running_models": running_names,
                "available_lanes": max(0, available_lanes),
                "ram_ok": ram_ok,
                "orphans_killed": orphans_killed,
                "unloaded": unloaded,
                "checked_at": time.time()
            }),
            "updated_at": "now()"
        }, upsert=True)
    except Exception:
        pass

    if orphans_killed or unloaded:
        print(f"[lane_scheduler] {hostname}: orphans_killed={orphans_killed} unloaded={unloaded} "
              f"running={len(running)} available={max(0, available_lanes)} ram_ok={ram_ok} "
              f"profile={profile.get('source')}({profile['max_ollama_lanes']}lanes/{profile.get('max_ollama_gb')}GB)")

    return {"available_lanes": max(0, available_lanes), "ram_ok": ram_ok}


def can_schedule_model(model_name):
    """Check if we can schedule this model on the current machine."""
    profile = _profile()
    running = _ollama_running_models()
    heavy = set(profile.get("heavy_models") or [])

    # Check lane capacity
    if len(running) >= profile["max_ollama_lanes"]:
        return False

    # Check if this is an exclusive/heavy model on THIS box
    if model_name in heavy:
        if running:  # can't run exclusive model alongside others
            return False

    # Check if any running model is exclusive (block all others)
    for r in running:
        if r.get("name", "") in heavy:
            return False

    return True


def acquire_lane(model_name):
    """Acquire a lane for a model. Returns True if granted."""
    if not can_schedule_model(model_name):
        # Try to free a lane
        running = _ollama_running_models()
        if running:
            # Unload the oldest idle model
            _unload_model(running[-1].get("name", ""))
            # Re-check
            if not can_schedule_model(model_name):
                return False
    return True


def release_lane(model_name):
    """Release a lane after model finishes."""
    _unload_model(model_name)


def _ollama_running_models():
    """Get currently running Ollama models."""
    try:
        r = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return []

        models = []
        for line in (r.stdout or "").splitlines()[1:]:  # skip header
            parts = line.split()
            if parts:
                models.append({"name": parts[0], "size": parts[1] if len(parts) > 1 else ""})
        return models
    except Exception:
        return []


def _unload_model(model_name):
    """Unload a specific model from Ollama."""
    if not model_name:
        return False
    try:
        import local_model_slots
        return local_model_slots.unload(model_name)
    except Exception:
        pass
    try:
        # Ollama doesn't have a direct unload command, but we can use the API
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({"model": model_name, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


def _unload_idle_models(running, profile):
    """Unload models that have been idle."""
    unloaded = 0
    max_gb = profile.get("max_ollama_gb", 16)

    # If we're over the RAM budget, unload the largest model
    total_gb = sum(_model_gb(m.get("size", "")) for m in running)

    if total_gb > max_gb and running:
        # Sort by size descending, unload largest first
        by_size = sorted(running, key=lambda m: -_model_gb(m.get("size", "")))
        for m in by_size:
            if total_gb <= max_gb:
                break
            if _unload_model(m.get("name", "")):
                total_gb -= _model_gb(m.get("size", ""))
                unloaded += 1

    return unloaded


def _kill_orphans(profile):
    """Kill orphaned Ollama-related processes."""
    killed = 0
    try:
        # Find ollama_llama_server processes that are orphaned
        r = subprocess.run(["pgrep", "-f", "ollama_llama_server"],
                          capture_output=True, text=True, timeout=10)
        pids = [p.strip() for p in (r.stdout or "").splitlines() if p.strip()]

        # Check if the main ollama serve process is running
        main = subprocess.run(["pgrep", "-f", "ollama serve"],
                             capture_output=True, text=True, timeout=10)
        main_running = bool(main.stdout.strip())

        if not main_running and pids:
            # Main process dead but workers alive = orphans
            for pid in pids:
                try:
                    subprocess.run(["kill", "-9", pid], capture_output=True, timeout=5)
                    killed += 1
                except Exception:
                    pass
    except Exception:
        pass

    return killed


def _check_ram_pressure():
    """Check if the system is under memory pressure. Delegates to resource_governor's
    macOS-accurate accounting (counts reclaimable file cache as available, unlike a raw
    free+speculative page count) instead of a second hand-rolled vm_stat parser."""
    try:
        import resource_governor
        free_gb = resource_governor.ram_free_gb()
        if free_gb is not None:
            return free_gb >= float(os.environ.get("RAM_FLOOR_GB", "4.0"))
    except Exception:
        pass
    try:
        r = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            output = r.stdout
            import re
            free_match = re.search(r"Pages free:\s+(\d+)", output)
            spec_match = re.search(r"Pages speculative:\s+(\d+)", output)
            free_pages = int(free_match.group(1)) if free_match else 0
            spec_pages = int(spec_match.group(1)) if spec_match else 0
            free_gb = (free_pages + spec_pages) * 16384 / (1024**3)
            min_free = float(os.environ.get("RAM_FLOOR_GB", "4.0"))
            return free_gb >= min_free
    except Exception:
        pass
    return True


def _model_gb(size_str):
    """Parse Ollama model size string to GB."""
    try:
        s = str(size_str).upper().strip()
        if "GB" in s:
            return float(s.replace("GB", "").strip())
        if "MB" in s:
            return float(s.replace("MB", "").strip()) / 1024
        return 0
    except (ValueError, AttributeError):
        return 0


if __name__ == "__main__":
    run()
