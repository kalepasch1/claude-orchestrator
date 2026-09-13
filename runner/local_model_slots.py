#!/usr/bin/env python3
"""Bounded, fail-closed local inference admission; never a reason to load or kill a model.

Every cooperating caller, including small models, shares one host lock. A busy or
unmeasurable host defers work through LocalCapacityError rather than generating
unslotted. Model residency is finite and coordinated by the request policy; a
resident model may belong to an interactive user, so admission never unloads it.
The older explicit RAM-relief helpers remain for their existing operator callers.
"""
import contextlib
import fcntl
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

LOCK = os.environ.get("ORCH_OLLAMA_SLOT_LOCK", "/tmp/orch-ollama-heavy.lock")
HEAVY_RAM_GB = float(os.environ.get("ORCH_OLLAMA_HEAVY_RAM_GB", "9"))
UNLOAD_FREE_GB = float(os.environ.get("ORCH_OLLAMA_UNLOAD_FREE_GB", "12"))


class LocalCapacityError(RuntimeError):
    """Temporary local unavailability; callers must defer, not retry outside the guard."""

    def __init__(self, reason="capacity_unavailable"):
        # Reasons are resource codes, never prompts, request bodies or exception text.
        self.reason = reason if re.fullmatch(r"[a-z_]+", str(reason)) else "capacity_unavailable"
        _capacity_receipt(self.reason)
        super().__init__("local inference deferred: " + self.reason)


def _capacity_receipt(reason):
    """Reason-only job receipt; its failure can never turn denial into admission.

    The scheduler creates the target in its private temporary directory. Reject
    unexpected paths, symlinks and non-owned files; replace the tiny receipt
    atomically so a caller that catches our exception cannot report false success.
    """
    path = os.environ.get("ORCH_LOCAL_CAPACITY_RECEIPT", "")
    name = os.path.basename(path)
    if not os.path.isabs(path) or not name.startswith("orch-local-capacity-") or not name.endswith(".json"):
        return
    temporary = None
    try:
        directory = os.path.dirname(path)
        parent = os.stat(directory, follow_symlinks=False)
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            return
        try:
            target = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(target.st_mode) or target.st_uid != os.getuid() or target.st_size > 4096:
                return
        except FileNotFoundError:
            pass
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, prefix=".capacity-", delete=False) as receipt:
            temporary = receipt.name
            json.dump({"deferred": True, "reason": reason}, receipt)
        os.replace(temporary, path)
        temporary = None
    except (OSError, ValueError):
        pass
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _number(name, default, low, high):
    try:
        value = float(os.environ.get(name, default))
        if not math.isfinite(value):
            return float(default)
        return min(high, max(low, value))
    except (TypeError, ValueError):
        return float(default)


def request_policy():
    """Hard bounds shared by memory estimates and the actual inference request."""
    max_ctx = int(_number("ORCH_OLLAMA_MAX_NUM_CTX", 4096, 256, 8192))
    max_predict = int(_number("ORCH_OLLAMA_MAX_NUM_PREDICT", 1024, 1, 4096))
    raw_keep = str(os.environ.get("ORCH_OLLAMA_KEEP_ALIVE", "60s")).strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smh]?)", raw_keep)
    keep = float(match[1]) * {"": 1, "s": 1, "m": 60, "h": 3600}[match[2]] if match else 60.0
    return {
        "num_ctx": int(_number("ORCH_OLLAMA_NUM_CTX", max_ctx, 256, max_ctx)),
        "num_predict": int(_number("ORCH_OLLAMA_NUM_PREDICT", max_predict, 1, max_predict)),
        "keep_alive": f"{int(min(120, keep))}s",
        "timeout_s": _number("ORCH_OLLAMA_REQUEST_TIMEOUT_S", 90, 1, 180),
    }


def _read_models(path):
    """Read metadata only, bounded in bytes and time. None means unknown, not empty."""
    try:
        with urllib.request.urlopen(_host() + path, timeout=2) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return None
        payload = json.loads(raw.decode())
        rows = payload.get("models") if isinstance(payload, dict) else None
        return rows if isinstance(rows, list) and all(isinstance(row, dict) for row in rows) else None
    except Exception:
        return None


def _resident_models():
    return _read_models("/api/ps")


def _pressure_level():
    """Kernel pressure, without resource_governor's unknown-is-healthy compatibility path."""
    try:
        if sys.platform.startswith("linux"):
            raw = _read_proc("/proc/pressure/memory")
            averages = {}
            for line in raw.splitlines():
                fields = line.split()
                if fields and fields[0] in ("some", "full"):
                    values = dict(item.split("=", 1) for item in fields[1:])
                    averages[fields[0]] = float(values["avg10"])
            if set(averages) != {"some", "full"} or any(not math.isfinite(v) or v < 0 or v > 100 for v in averages.values()):
                return None
            # PSI is percent wall-time stalled on memory in the last 10 seconds.
            # Even sustained minor reclaim stalls defer background local work.
            if averages["full"] >= 1 or averages["some"] >= 10:
                return 4
            return 2 if averages["full"] >= 0.1 or averages["some"] >= 1 else 1
        if sys.platform != "darwin":
            return None
        value = subprocess.check_output(
            ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
            stderr=subprocess.DEVNULL, timeout=2, text=True,
        )
        return int(value.strip())
    except Exception:
        return None


def _read_proc(path):
    with open(path, encoding="ascii") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("telemetry too large")
    return raw


def _same_model(left, right):
    def canonical(value):
        value = str(value or "").strip()
        return value if ":" in value else value + ":latest"
    return canonical(left) == canonical(right)


def _positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def _load_per_core():
    try:
        cores = os.cpu_count()
        load = os.getloadavg()[0]
        return load / cores if cores else None
    except (OSError, ValueError, TypeError):
        return None


def host_admission_status(*, free_fn=None, pressure_fn=None, load_fn=None):
    """Read-only host health for job launch, without querying/reserving any model.

    All memory fields and legacy *_GB policy values here are GiB (not the
    resource governor's decimal GB). Native byte telemetry is converted exactly
    once in _free_ram_gb; injected free_fn values must already be GiB.
    Unknown telemetry always defers admission.
    """
    headroom = _number("ORCH_OLLAMA_ADMIT_HEADROOM_GB", 8, 8, 64)
    ceiling = _number("ORCH_OLLAMA_MAX_LOAD_PER_CORE", 1.5, 0.25, 4)
    result = {"admitted": False, "reason": "telemetry_unknown", "unit": "GiB",
              "free_gb": None, "headroom_gb": headroom, "pressure": None,
              "load_per_core": None, "max_load_per_core": ceiling}
    try:
        raw_free = (free_fn or _free_ram_gb)()
        free = float(raw_free) if raw_free is not None else None
        pressure = (pressure_fn or _pressure_level)()
        raw_load = (load_fn or _load_per_core)()
        load = float(raw_load) if raw_load is not None else None
    except Exception:
        return result
    if isinstance(raw_free, bool) or isinstance(raw_load, bool) or isinstance(pressure, bool) or free is None or not math.isfinite(free) or free < 0 or load is None or not math.isfinite(load) or load < 0 or pressure not in (1, 2, 4):
        return result
    result.update(free_gb=free, pressure=pressure, load_per_core=load)
    if pressure != 1:
        return {**result, "reason": "memory_pressure"}
    if free < headroom:
        return {**result, "reason": "host_headroom"}
    if load > ceiling:
        return {**result, "reason": "host_load"}
    return {**result, "admitted": True, "reason": "ok"}


def _estimated_allocation_gb(model):
    """Disk weights plus context allowance; conservative name estimate when metadata is absent."""
    kv_allowance = 2.0 * request_policy()["num_ctx"] / 4096.0
    for row in _read_models("/api/tags") or []:
        if _same_model(row.get("model") or row.get("name"), model):
            size = _positive(row.get("size"))
            if size is not None:
                return size / (1024 ** 3) * 1.2 + kv_allowance
    match = re.search(r"(?:^|[:/\-])(\d+(?:\.\d+)?)b(?:$|[\-:])", str(model).lower())
    if match:
        return max(2.0, float(match[1]) * 0.75) + kv_allowance
    if model in RAM_GB:
        return float(RAM_GB[model]) + kv_allowance
    # An alias with unknown weights could be a 70B model. Never guess that it is small.
    return None


def admission_status(model, *, free_fn=None, pressure_fn=None, load_fn=None, resident_fn=None):
    """Read-only preflight for schedulers; slot() rechecks under the host lock.

    A caller already using another resident model is not evicted. Actual resident
    allocation is counted once; reusing it still requires the host's free headroom.
    """
    cap = _number("ORCH_OLLAMA_MAX_ALLOCATION_GB", 8, 1, 64)
    host = host_admission_status(free_fn=free_fn, pressure_fn=pressure_fn, load_fn=load_fn)
    result = {**host, "admitted": False, "allocation_gb": None,
              "additional_gb": None, "max_allocation_gb": cap}
    if not isinstance(model, str) or not model.strip():
        return {**result, "reason": "model_unknown"}
    if not host["admitted"]:
        return result
    free, headroom = host["free_gb"], host["headroom_gb"]
    try:
        resident = (resident_fn or _resident_models)()
    except Exception:
        return {**result, "reason": "telemetry_unknown"}
    if resident is None:
        return {**result, "reason": "telemetry_unknown"}
    if not isinstance(resident, list) or any(not isinstance(row, dict) for row in resident):
        return {**result, "reason": "telemetry_unknown"}
    matches = []
    for row in resident:
        name = row.get("model") or row.get("name")
        if not name:
            return {**result, "reason": "telemetry_unknown"}
        if not _same_model(name, model):
            return {**result, "reason": "other_model_resident"}
        matches.append(row)
    if len(matches) > 1:
        return {**result, "reason": "telemetry_unknown"}
    if matches:
        row = matches[0]
        measurements = [_positive(row.get(key)) for key in ("size", "size_vram")]
        measured = max([value for value in measurements if value is not None], default=0)
        if not measured:
            return {**result, "reason": "model_memory_unknown"}
        allocation = measured / (1024 ** 3)
        loaded_ctx = _positive(row.get("context_length"))
        # Expanding an existing KV cache is a new allocation. Without a measured
        # matching context, reserve the conservative full estimated footprint.
        estimate = _estimated_allocation_gb(model) if not loaded_ctx or loaded_ctx < request_policy()["num_ctx"] else allocation
        if estimate is None:
            return {**result, "reason": "model_memory_unknown"}
        allocation = max(allocation, estimate)
        additional = max(0.0, allocation - measured / (1024 ** 3))
    else:
        allocation = _estimated_allocation_gb(model)
        if allocation is None:
            return {**result, "reason": "model_memory_unknown"}
        additional = allocation
    result.update(allocation_gb=round(allocation, 3), additional_gb=round(additional, 3))
    if allocation > cap:
        return {**result, "reason": "model_allocation_limit"}
    if free < headroom + additional:
        return {**result, "reason": "host_headroom"}
    return {**result, "admitted": True, "reason": "ok"}

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
    """Bounded native available-memory reads, returned in GiB, not decimal GB."""
    try:
        if sys.platform.startswith("linux"):
            raw = _read_proc("/proc/meminfo")
            values = {}
            for name in ("MemTotal", "MemAvailable"):
                match = re.search(r"^" + name + r":\s+(\d+)\s+kB\s*$", raw, re.MULTILINE)
                if not match:
                    return None
                values[name] = int(match[1]) * 1024
            total, available = values["MemTotal"], values["MemAvailable"]
        elif sys.platform == "darwin":
            total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"],
                        timeout=2, stderr=subprocess.DEVNULL, text=True).strip())
            raw = subprocess.check_output(["vm_stat"], timeout=2, stderr=subprocess.DEVNULL, text=True)
            match = re.search(r"page size of (\d+) bytes", raw)
            if not match or int(match[1]) <= 0:
                return None
            page = int(match[1])
            used = 0
            for name in ("Anonymous pages", "Pages wired down", "Pages occupied by compressor"):
                match = re.search(r"^" + re.escape(name) + r":\s+(\d+)\.", raw, re.MULTILINE)
                if not match:
                    return None
                used += int(match[1]) * page
            available = total - used
        else:
            return None
        if total <= 0 or available < 0 or available > total:
            return None
        return available / (1024 ** 3)
    except Exception:
        return None


def maybe_unload_after(model):
    """Compatibility hook: finite request residency replaces unconditional unloading.

    A completed HTTP request does not prove that another client is not using the
    resident model. Resource admission must never terminate that client's work.
    """
    return False


def _wait_admission(model, free_fn=None, sleep_fn=time.sleep, now_fn=time.monotonic):
    max_wait = _number("ORCH_OLLAMA_ADMIT_WAIT_S", 0, 0, 5)
    start = now_fn()
    while True:
        status = admission_status(model, free_fn=free_fn)
        elapsed = now_fn() - start
        if status["admitted"] or elapsed >= max_wait or status["reason"] != "host_headroom":
            return status, elapsed
        sleep_fn(min(0.25, max_wait - elapsed))


def wait_for_ram(model, free_fn=None, sleep_fn=time.sleep, now_fn=time.monotonic):
    """Compatibility result: zero wait checks once; unknown/unsafe capacity is False."""
    status, waited = _wait_admission(model, free_fn, sleep_fn, now_fn)
    return status["admitted"], waited


def _slot_wait_s():
    """A short acquisition budget; zero attempts once, never disables locking."""
    return _number("ORCH_OLLAMA_SLOT_WAIT_S", 1, 0, 5)


def _log_slot(msg, *args):
    """Never let a diagnostic raise on the resource path."""
    try:
        import logging
        logging.getLogger(__name__).warning(msg, *args)
    except Exception:
        pass


@contextlib.contextmanager
def slot(model, operation="local_completion"):
    # Legacy scheduler/memory-gate switches cannot disable this safety boundary.
    try:
        lock_dir = os.path.dirname(LOCK)
        if lock_dir:
            os.makedirs(lock_dir, exist_ok=True)
        lock = open(LOCK, "a+")
    except (OSError, TypeError):
        raise LocalCapacityError("slot_unavailable") from None
    acquired = False
    try:
        started = time.monotonic()
        budget = _slot_wait_s()
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                elapsed = time.monotonic() - started
                if elapsed >= budget:
                    raise LocalCapacityError("slot_busy") from None
                time.sleep(min(0.1, budget - elapsed))
            except OSError:
                raise LocalCapacityError("slot_unavailable") from None
        status, _ = _wait_admission(model)
        if not status["admitted"]:
            raise LocalCapacityError(status["reason"])
        yield {**status, "locked": True, "waited_ms": int((time.monotonic() - started) * 1000), "unloaded": []}
    except LocalCapacityError as error:
        _log_slot("local inference deferred (%s)", error.reason)
        raise
    finally:
        if acquired:
            try:
                fcntl.flock(lock, fcntl.LOCK_UN)
            except OSError:
                pass  # Closing the descriptor also releases its lock.
        lock.close()
