#!/usr/bin/env python3
"""
error_remediation.py — AI-powered error detection and config rollback.

Classifies errors into categories, tracks error rates per module, and
auto-disables modules whose error rate exceeds a threshold by toggling
ORCH_{MODULE}_ENABLED=false. Feature-flagged via ORCH_ERROR_REMEDIATION_ENABLED
(default false).

Fail-soft: every public function is wrapped so that a bug in this module
never takes down the runner.
"""
import os, sys, time, re, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Feature flag ──────────────────────────────────────────────────────────────
def _enabled():
    return os.environ.get("ORCH_ERROR_REMEDIATION_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# ── Configuration ─────────────────────────────────────────────────────────────
ERROR_WINDOW_S    = int(os.environ.get("ORCH_ERROR_WINDOW_S", "300"))      # sliding window
ERROR_THRESHOLD   = int(os.environ.get("ORCH_ERROR_THRESHOLD", "5"))       # errors/window
ROLLBACK_COOLDOWN = int(os.environ.get("ORCH_ROLLBACK_COOLDOWN_S", "600"))  # min gap between rollbacks

# ── Error category patterns ──────────────────────────────────────────────────
_CATEGORY_PATTERNS = {
    "transient": [
        re.compile(r"timeout|timed?\s*out|ETIMEDOUT|ECONNRESET|ECONNREFUSED", re.I),
        re.compile(r"429|rate.limit|too many requests|overloaded|retry", re.I),
        re.compile(r"503|502|504|service.unavailable|bad.gateway", re.I),
    ],
    "config": [
        re.compile(r"missing.env|env.var|not.configured|invalid.config", re.I),
        re.compile(r"ORCH_.*not set|undefined.variable|KeyError.*ORCH", re.I),
        re.compile(r"permission.denied|access.denied|forbidden|401|403", re.I),
    ],
    "dependency": [
        re.compile(r"ModuleNotFoundError|ImportError|No module named", re.I),
        re.compile(r"command not found|ENOENT|FileNotFoundError", re.I),
        re.compile(r"package.*not installed|pip install|npm install", re.I),
    ],
    "code": [
        re.compile(r"SyntaxError|IndentationError|TabError", re.I),
        re.compile(r"TypeError|AttributeError|NameError|ValueError", re.I),
        re.compile(r"AssertionError|ZeroDivisionError|RecursionError", re.I),
    ],
}

# ── Module-level state (singleton) ───────────────────────────────────────────
_lock = threading.Lock()
_error_log = []           # list of (timestamp, module_name, category, snippet)
_rollbacks = {}           # module_name -> {"at": timestamp, "reason": str}
_classify_counts = {"transient": 0, "config": 0, "dependency": 0, "code": 0, "unknown": 0}
_remediation_calls = 0
_rollback_count = 0


# ── Public API ────────────────────────────────────────────────────────────────

def classify_error(error_text: str) -> str:
    """Classify an error string into a category.

    Returns one of: transient, config, dependency, code, unknown.
    """
    if not error_text:
        return "unknown"
    text = str(error_text)
    for category, patterns in _CATEGORY_PATTERNS.items():
        for pat in patterns:
            if pat.search(text):
                with _lock:
                    _classify_counts[category] += 1
                return category
    with _lock:
        _classify_counts["unknown"] += 1
    return "unknown"


def record_error(module_name: str, error_text: str) -> str:
    """Record an error occurrence and return its classification.

    Adds the error to the sliding window log for threshold tracking.
    """
    category = classify_error(error_text)
    now = time.time()
    snippet = str(error_text)[:200]
    with _lock:
        _error_log.append((now, module_name, category, snippet))
        # prune entries older than the window
        cutoff = now - ERROR_WINDOW_S
        while _error_log and _error_log[0][0] < cutoff:
            _error_log.pop(0)
    return category


def _module_error_count(module_name: str) -> int:
    """Count errors for a module within the sliding window."""
    cutoff = time.time() - ERROR_WINDOW_S
    with _lock:
        return sum(1 for ts, mod, _, _ in _error_log if mod == module_name and ts >= cutoff)


def rollback_config(module_name: str, reason: str = "") -> bool:
    """Disable a module by setting ORCH_{MODULE}_ENABLED=false.

    Returns True if the rollback was applied, False if skipped (cooldown or
    already rolled back).
    """
    global _rollback_count
    if not _enabled():
        return False
    key = module_name.upper().replace("-", "_").replace(".", "_")
    env_key = f"ORCH_{key}_ENABLED"
    now = time.time()
    with _lock:
        prev = _rollbacks.get(module_name)
        if prev and (now - prev["at"]) < ROLLBACK_COOLDOWN:
            return False  # cooldown
        os.environ[env_key] = "false"
        _rollbacks[module_name] = {"at": now, "reason": reason or "threshold exceeded",
                                    "env_key": env_key}
        _rollback_count += 1
    print(f"[error-remediation] rolled back {module_name}: set {env_key}=false ({reason})")
    return True


def maybe_trigger_remediation(error_log: str = "", module_name: str = "") -> dict:
    """Check error rates and trigger rollback if threshold exceeded.

    Can be called periodically (every 30s) from the runner's main loop.
    Returns a dict describing what happened.
    """
    global _remediation_calls
    with _lock:
        _remediation_calls += 1

    if not _enabled():
        return {"action": "disabled", "detail": "ORCH_ERROR_REMEDIATION_ENABLED is false"}

    # If called with an error_log string, record it first
    if error_log and module_name:
        record_error(module_name, error_log)

    # Check all modules in the current window for threshold breach
    cutoff = time.time() - ERROR_WINDOW_S
    module_counts = {}
    with _lock:
        for ts, mod, cat, _ in _error_log:
            if ts >= cutoff:
                module_counts[mod] = module_counts.get(mod, 0) + 1

    rolled_back = []
    for mod, count in module_counts.items():
        if count >= ERROR_THRESHOLD:
            if rollback_config(mod, reason=f"{count} errors in {ERROR_WINDOW_S}s window"):
                rolled_back.append(mod)

    if rolled_back:
        return {"action": "rollback", "modules": rolled_back}
    return {"action": "none", "module_counts": module_counts}


def remediation_status() -> dict:
    """Return current remediation state: rolled-back modules, active errors, config."""
    cutoff = time.time() - ERROR_WINDOW_S
    with _lock:
        active_errors = [(mod, cat, snip) for ts, mod, cat, snip in _error_log if ts >= cutoff]
        rollbacks_copy = dict(_rollbacks)
    return {
        "enabled": _enabled(),
        "active_errors": len(active_errors),
        "rolled_back_modules": {mod: rb["reason"] for mod, rb in rollbacks_copy.items()},
        "error_window_s": ERROR_WINDOW_S,
        "error_threshold": ERROR_THRESHOLD,
        "rollback_cooldown_s": ROLLBACK_COOLDOWN,
    }


def stats() -> dict:
    """Return module statistics for observability."""
    with _lock:
        classify_copy = dict(_classify_counts)
        log_len = len(_error_log)
        rollbacks_copy = dict(_rollbacks)
    return {
        "enabled": _enabled(),
        "classifications": classify_copy,
        "errors_in_window": log_len,
        "rollbacks": {mod: rb["reason"] for mod, rb in rollbacks_copy.items()},
        "rollback_count": _rollback_count,
        "remediation_calls": _remediation_calls,
    }


# ── Fail-soft periodic entry point ───────────────────────────────────────────
_last_periodic_run = 0.0

def periodic_check():
    """Called from the runner's main loop every ~30 seconds.

    Fail-soft: catches all exceptions so the runner never crashes.
    """
    global _last_periodic_run
    try:
        if not _enabled():
            return
        now = time.time()
        if now - _last_periodic_run < 25:  # debounce
            return
        _last_periodic_run = now
        result = maybe_trigger_remediation()
        if result.get("action") == "rollback":
            print(f"[error-remediation] periodic rollback: {result.get('modules')}")
    except Exception as e:
        print(f"[error-remediation] periodic_check failed (fail-soft): {e}")
