#!/usr/bin/env python3
"""Local Ollama model slot scheduling and RAM relief.

Only one heavy local model should be loaded at a time on a Mac. This module
serializes heavy Ollama calls with a file lock and unloads other resident models
before loading the requested one. It is deliberately local-only; each Mac enforces
its own slot while fleet_config controls the shared knobs.
"""
import contextlib
import fcntl
import json
import os
import signal
import subprocess
import time
import urllib.request

LOCK = os.environ.get("ORCH_OLLAMA_SLOT_LOCK", "/tmp/orch-ollama-heavy.lock")
HEAVY_RAM_GB = float(os.environ.get("ORCH_OLLAMA_HEAVY_RAM_GB", "9"))
UNLOAD_FREE_GB = float(os.environ.get("ORCH_OLLAMA_UNLOAD_FREE_GB", "12"))

RAM_GB = {
    "qwen3-coder:30b": 24,
    "deepseek-coder-v2:16b": 12,
    "codestral:22b": 16,
    "gemma3:27b": 22,
    "gemma3:12b": 10,
    "sorc/qwen3.5-claude-4.6-opus:latest": 16,
    "llama3.1:latest": 9,
    "llama3.1": 9,
}


def _truthy(name, default=True):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _host():
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").split()[0].rstrip("/")


def ram_gb(model):
    if model in RAM_GB:
        return RAM_GB[model]
    low = str(model or "").lower()
    if any(x in low for x in ("30b", "32b", "34b")):
        return 24
    if any(x in low for x in ("22b", "27b")):
        return 16
    if any(x in low for x in ("12b", "16b")):
        return 10
    return 6


def is_heavy(model):
    return ram_gb(model) >= HEAVY_RAM_GB


def loaded_models():
    try:
        with urllib.request.urlopen(_host() + "/api/ps", timeout=3) as r:
            data = json.loads(r.read().decode())
        return [m.get("model") or m.get("name") for m in data.get("models", []) if m.get("model") or m.get("name")]
    except Exception:
        try:
            raw = subprocess.check_output(["curl", "-s", _host() + "/api/ps"], timeout=5).decode()
            data = json.loads(raw or "{}")
            return [m.get("model") or m.get("name") for m in data.get("models", []) if m.get("model") or m.get("name")]
        except Exception:
            return []


def _post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(_host() + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def unload(model):
    if not model:
        return False
    try:
        _post("/api/generate", {"model": model, "prompt": "", "stream": False, "keep_alive": 0})
        time.sleep(0.5)
        if model not in loaded_models():
            return True
    except Exception:
        pass
    try:
        body = json.dumps({"model": model, "prompt": "", "stream": False, "keep_alive": 0})
        subprocess.check_output(["curl", "-s", _host() + "/api/generate", "-d", body], timeout=10)
        time.sleep(0.5)
        if model not in loaded_models():
            return True
    except Exception:
        pass
    try:
        # Newer Ollama builds support `ollama stop`; it is the most reliable immediate unload.
        subprocess.run(["ollama", "stop", model], capture_output=True, timeout=15)
        time.sleep(0.5)
        if model not in loaded_models():
            return True
    except Exception:
        pass
    if _truthy("ORCH_OLLAMA_FORCE_KILL_STUCK_SERVER", True):
        if _kill_llama_servers():
            time.sleep(1.0)
            return model not in loaded_models()
    return False


def _kill_llama_servers():
    """Last-resort RAM relief for Ollama child processes that ignore keep_alive/stop."""
    killed = 0
    try:
        out = subprocess.check_output(["ps", "-axo", "pid,args"], text=True, timeout=5)
    except Exception:
        return False
    for line in out.splitlines()[1:]:
        if "llama-server" not in line or "Ollama.app" not in line:
            continue
        try:
            pid = int(line.strip().split(None, 1)[0])
        except Exception:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except ProcessLookupError:
            pass
        except Exception:
            continue
    if not killed:
        return False
    deadline = time.time() + 5
    while time.time() < deadline:
        if not any("llama-server" in line and "Ollama.app" in line
                   for line in (subprocess.getoutput("ps -axo pid,args") or "").splitlines()):
            return True
        time.sleep(0.3)
    for line in (subprocess.getoutput("ps -axo pid,args") or "").splitlines()[1:]:
        if "llama-server" not in line or "Ollama.app" not in line:
            continue
        try:
            os.kill(int(line.strip().split(None, 1)[0]), signal.SIGKILL)
        except Exception:
            pass
    return True


def unload_others(model):
    if not _truthy("ORCH_OLLAMA_UNLOAD_OTHERS", True):
        return []
    unloaded = []
    for loaded in loaded_models():
        if loaded != model and is_heavy(loaded):
            if unload(loaded):
                unloaded.append(loaded)
    return unloaded


def _free_ram_gb():
    try:
        import resource_governor
        return resource_governor.ram_free_gb()
    except Exception:
        return None


def maybe_unload_after(model):
    if not is_heavy(model):
        return False
    if not _truthy("ORCH_OLLAMA_UNLOAD_AFTER_HEAVY", True):
        return False
    if not _truthy("ORCH_OLLAMA_KEEP_HEAVY_RESIDENT", False):
        return unload(model)
    free = _free_ram_gb()
    if free is None or free < UNLOAD_FREE_GB:
        return unload(model)
    return False


def wait_for_ram(model, free_fn=None, sleep_fn=time.sleep, now_fn=time.time):
    """Admission gate: wait (bounded) until free RAM fits the model + headroom.

    Loading a 24GB coder while node lanes hold the RAM guarantees a sentinel ram-clamp
    mid-generation, a caller retry, and a reload — the observed clamp/reload thrash loop
    (2026-07-09/10). Waiting a bounded time for lanes to drain breaks the loop. Fail-soft:
    on timeout or if free RAM can't be read, admit anyway (sentinel remains the backstop).
    Returns (admitted_clean, waited_s)."""
    try:
        headroom = float(os.environ.get("ORCH_OLLAMA_ADMIT_HEADROOM_GB", "3"))
        max_wait = float(os.environ.get("ORCH_OLLAMA_ADMIT_WAIT_S", "90"))
    except ValueError:
        headroom, max_wait = 3.0, 90.0
    if max_wait <= 0:
        return True, 0.0
    if free_fn is None:
        free_fn = _free_ram_gb
    need = ram_gb(model) + headroom
    start = now_fn()
    while True:
        free = None
        try:
            free = free_fn()
        except Exception:
            pass
        if free is None or free >= need:
            return True, now_fn() - start
        if now_fn() - start >= max_wait:
            return False, now_fn() - start
        sleep_fn(min(5.0, max(0.1, max_wait / 6)))


@contextlib.contextmanager
def slot(model, operation="local_completion"):
    if not is_heavy(model) or not _truthy("ORCH_OLLAMA_SLOT_SCHEDULER", True):
        yield {"locked": False, "unloaded": []}
        return
    lock_dir = os.path.dirname(LOCK)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    with open(LOCK, "a+") as f:
        start = time.time()
        fcntl.flock(f, fcntl.LOCK_EX)
        waited_ms = int((time.time() - start) * 1000)
        unloaded = unload_others(model)
        admitted, ram_waited_s = wait_for_ram(model)
        if not admitted:
            try:
                import db
                db.insert("resource_events", {
                    "kind": "ollama_admit_timeout", "value": int(ram_waited_s),
                    "detail": f"{operation} {model}",
                    "action": "admitted anyway after bounded wait (fail-soft)",
                })
            except Exception:
                pass
        try:
            yield {"locked": True, "waited_ms": waited_ms, "unloaded": unloaded}
        finally:
            unloaded_self = maybe_unload_after(model)
            try:
                if waited_ms or unloaded or unloaded_self:
                    import db
                    db.insert("resource_events", {
                        "kind": "ollama_slot",
                        "value": waited_ms,
                        "detail": f"{operation} {model}",
                        "action": f"unloaded={','.join(unloaded) or '-'} self_unloaded={unloaded_self}",
                    })
            except Exception:
                pass
            fcntl.flock(f, fcntl.LOCK_UN)
