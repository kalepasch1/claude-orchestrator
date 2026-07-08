"""
lane_scheduler.py — local model lane scheduler.

Mac-aware scheduling for Ollama and other local models:
1. Mac 1 is memory constrained → carries fewer local model lanes
2. Mac 2 has more RAM → carries more Ollama load
3. Heavy Ollama models run one-at-a-time with guaranteed unload
4. Orphan process cleanup prevents RAM thrash

Protects throughput from RAM thrash by treating local model capacity
as a managed resource.
"""
import os, sys, subprocess, json, socket, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Machine profiles — tune per Mac
MACHINE_PROFILES = {
    "Mac.lan": {
        "max_ollama_lanes": 1,
        "max_ollama_gb": 8,
        "heavy_models": ["deepseek-coder-v2", "codellama:34b", "qwen2.5-coder:32b"],
    },
    "Mandys-MacBook-Pro.local": {
        "max_ollama_lanes": 3,
        "max_ollama_gb": 24,
        "heavy_models": [],
    }
}

# Models that need exclusive access (too large to share RAM)
EXCLUSIVE_MODELS = set(os.environ.get("ORCH_EXCLUSIVE_OLLAMA_MODELS",
    "deepseek-coder-v2,codellama:34b,qwen2.5-coder:32b").split(","))

HEAVY_MODEL_GB = float(os.environ.get("ORCH_HEAVY_MODEL_GB", "8"))


def run():
    """Periodic entry: manage local model lanes and cleanup orphans."""
    hostname = socket.gethostname()
    profile = MACHINE_PROFILES.get(hostname, {
        "max_ollama_lanes": 2,
        "max_ollama_gb": 16,
        "heavy_models": []
    })

    # 1. Check current Ollama state
    running = _ollama_running_models()

    # 2. Kill orphan processes
    orphans_killed = _kill_orphans(profile)

    # 3. Unload idle models to free RAM
    unloaded = _unload_idle_models(running, profile)

    # 4. Check RAM pressure
    ram_ok = _check_ram_pressure(profile)

    # 5. Report lane availability
    available_lanes = profile["max_ollama_lanes"] - len(running)

    try:
        db.insert("controls", {
            "key": f"lane_scheduler_{hostname}",
            "value": json.dumps({
                "hostname": hostname,
                "max_ollama_lanes": profile["max_ollama_lanes"],
                "running_models": [m.get("name", "") for m in running],
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
              f"running={len(running)} available={max(0, available_lanes)} ram_ok={ram_ok}")

    return {"available_lanes": max(0, available_lanes), "ram_ok": ram_ok}


def can_schedule_model(model_name):
    """Check if we can schedule this model on the current machine."""
    hostname = socket.gethostname()
    profile = MACHINE_PROFILES.get(hostname, {"max_ollama_lanes": 2, "max_ollama_gb": 16, "heavy_models": []})

    running = _ollama_running_models()

    # Check lane capacity
    if len(running) >= profile["max_ollama_lanes"]:
        return False

    # Check if this is an exclusive model
    if model_name in EXCLUSIVE_MODELS:
        if running:  # can't run exclusive model alongside others
            return False

    # Check if any running model is exclusive (block all others)
    for r in running:
        if r.get("name", "") in EXCLUSIVE_MODELS:
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


def _check_ram_pressure(profile):
    """Check if the system is under memory pressure."""
    try:
        r = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            output = r.stdout
            # Parse "Pages free" and "Pages speculative"
            import re
            free_match = re.search(r"Pages free:\s+(\d+)", output)
            spec_match = re.search(r"Pages speculative:\s+(\d+)", output)

            free_pages = int(free_match.group(1)) if free_match else 0
            spec_pages = int(spec_match.group(1)) if spec_match else 0

            # Each page is 16KB on Apple Silicon
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
