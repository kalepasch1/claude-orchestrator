#!/usr/bin/env python3
"""
model_pool_cache.py - keep local Ollama warm and cache stable prompt prefixes to cut
per-call latency and tokens across providers.

Two mechanisms:
  1. Warm-ping: periodically sends a tiny completion to the local Ollama model so it stays
     resident in memory (avoids cold-start on first real call).
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


# ── Ollama warm-ping ──────────────────────────────────────────────────────────

def _ping_ollama() -> bool:
    """Send a trivial completion to keep the model resident."""
    try:
        payload = json.dumps({"model": OLLAMA_MODEL, "prompt": "ping", "stream": False,
                              "options": {"num_predict": 1}}).encode()
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/generate",
                                    data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def warm(force: bool = False) -> bool:
    """Warm the local model if interval has elapsed. Returns True if ping succeeded."""
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
