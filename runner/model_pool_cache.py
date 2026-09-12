#!/usr/bin/env python3
"""
model_pool_cache.py - observe local Ollama residency and cache stable prompt prefixes.

Two mechanisms:
  1. Residency probe: observe a model already loaded by useful work. A background
     cache must not load models or keep them resident after useful work has ended.
  2. Prefix cache: stores the SHA-256 of stable system-prompt prefixes and their token counts
     so callers can skip re-sending unchanged preamble when the provider supports prompt caching.

Thread-safe singleton. Fail-soft: returns empty/defaults on any error.
"""
import os, sys, hashlib, threading, time, json, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
WARM_INTERVAL = int(os.environ.get("MODEL_POOL_WARM_INTERVAL", "300"))  # seconds
PREFIX_CACHE_MAX = int(os.environ.get("PREFIX_CACHE_MAX", "128"))

_lock = threading.Lock()
_prefix_cache: dict = {}   # sha256 -> {"tokens": int, "ts": float}
_last_warm: float = 0.0
_warm_ok: bool = False


# ── prefix cache ──────────────────────────────────────────────────────────────

def cache_prefix(text: str, token_count: int) -> str:
    """Register a stable prompt prefix and its token count. Returns the cache key."""
    if not text:
        return ""
    key = hashlib.sha256(text.encode(errors="replace")).hexdigest()[:16]
    with _lock:
        _prefix_cache[key] = {"tokens": token_count, "ts": time.time()}
        # evict oldest if over limit
        if len(_prefix_cache) > PREFIX_CACHE_MAX:
            oldest = min(_prefix_cache, key=lambda k: _prefix_cache[k]["ts"])
            _prefix_cache.pop(oldest, None)
    return key


def get_prefix(key: str) -> dict:
    """Look up a cached prefix. Returns {"tokens": int, "ts": float} or {}."""
    with _lock:
        return dict(_prefix_cache.get(key, {}))


def invalidate(key: str = "") -> None:
    """Remove one key or clear all."""
    with _lock:
        if key:
            _prefix_cache.pop(key, None)
        else:
            _prefix_cache.clear()


# ── Ollama residency probe (legacy warm() API) ─────────────────────────────────

def _ping_ollama() -> bool:
    """Read residency without inference, model loading, or keep-alive renewal."""
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST.rstrip('/')}/api/ps")
        with urllib.request.urlopen(req, timeout=2) as resp:
            raw = resp.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return False
        data = json.loads(raw)
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return False
        def canonical(model):
            model = str(model or "")
            return model if ":" in model else model + ":latest"
        return any(isinstance(row, dict) and
                   canonical(row.get("model") or row.get("name")) == canonical(OLLAMA_MODEL)
                   for row in models)
    except Exception:
        return False


def warm(force: bool = False) -> bool:
    """Check existing residency on the old warm cadence; never start inference."""
    global _last_warm, _warm_ok
    now = time.time()
    if not force and (now - _last_warm) < WARM_INTERVAL:
        return _warm_ok
    _warm_ok = _ping_ollama()
    _last_warm = now
    return _warm_ok


# ── stats ─────────────────────────────────────────────────────────────────────

def stats() -> dict:
    with _lock:
        return {
            "cached_prefixes": len(_prefix_cache),
            "last_warm": _last_warm,
            "warm_ok": _warm_ok,
            "ollama_model": OLLAMA_MODEL,
        }


# ── CLI entry ─────────────────────────────────────────────────────────────────

def run():
    """Warm Ollama and print stats."""
    ok = warm(force=True)
    print(f"model_pool_cache: warm={'ok' if ok else 'FAIL'}, stats={json.dumps(stats())}")
    return ok


if __name__ == "__main__":
    run()
