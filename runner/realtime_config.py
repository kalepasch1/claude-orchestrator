#!/usr/bin/env python3
"""realtime_config.py - Cached config accessor for fleet parameters."""
import os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
_cache, _cache_ts, _TTL = {}, 0.0, float(os.environ.get("CONFIG_CACHE_TTL", "10"))
_lock = threading.Lock()
def get(key, default=None):
    global _cache, _cache_ts
    if time.time() - _cache_ts > _TTL: _refresh()
    return _cache.get(key, default)
def _refresh():
    global _cache, _cache_ts
    with _lock:
        try:
            rows = db.select("fleet_config", {"select": "key,value"}) or []
        except Exception:
            rows = []
        _cache = {r["key"]: r["value"] for r in rows}
        _cache_ts = time.time()
