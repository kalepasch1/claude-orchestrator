#!/usr/bin/env python3
"""
config_sync_realtime.py — real-time configuration synchronization.

Subscribes to Supabase Realtime changes on the fleet_config table so config
updates propagate instantly instead of waiting for the next poll interval.
Falls back to direct DB queries when realtime is unavailable.

Usage:
    from config_sync_realtime import get_config, start, stop

    start()                       # begin listening (non-blocking)
    val = get_config("MAX_PARALLEL")  # read from cache or DB
    stop()                        # tear down

Thread-safe. Fail-soft: errors are logged, never raised to callers.
"""
import os
import sys
import json
import time
import logging
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("config_sync_realtime")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CACHE_TTL_S = float(os.environ.get("ORCH_CONFIG_CACHE_TTL_S", "60"))
RECONNECT_DELAY_S = float(os.environ.get("ORCH_RT_RECONNECT_DELAY_S", "5"))
MAX_RECONNECT_DELAY_S = float(os.environ.get("ORCH_RT_MAX_RECONNECT_DELAY_S", "120"))

# ---------------------------------------------------------------------------
# In-memory cache with TTL
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_cache = {}  # key -> (value, timestamp)
_realtime_connected = False
_listener_thread = None
_stop_event = threading.Event()

# Stats for observability
_stats = {"cache_hits": 0, "cache_misses": 0, "rt_events": 0,
          "db_fallbacks": 0, "errors": 0}


def stats():
    """Return a snapshot of operational counters."""
    with _lock:
        return dict(_stats)


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------
def _cache_get(key):
    """Read from cache. Returns (value_or_None, hit: bool)."""
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None, False
        value, ts = entry
        if _realtime_connected or (time.time() - ts < CACHE_TTL_S):
            _stats["cache_hits"] += 1
            return value, True
        # Expired and no realtime keeping it fresh
        del _cache[key]
        return None, False


def _cache_set(key, value):
    with _lock:
        _cache[key] = (value, time.time())


def _cache_delete(key):
    with _lock:
        _cache.pop(key, None)


def _cache_bulk_load(rows):
    """Populate cache from a full table fetch."""
    now = time.time()
    with _lock:
        for row in rows:
            k = row.get("key")
            v = row.get("value")
            if k is not None and v is not None:
                _cache[k] = (str(v), now)


# ---------------------------------------------------------------------------
# DB fallback
# ---------------------------------------------------------------------------
def _db_get(key):
    """Fetch a single key from fleet_config via the existing db module."""
    try:
        import db
        rows = db.select("fleet_config", {"key": "eq." + key, "select": "value", "limit": "1"})
        if rows and len(rows) > 0:
            return str(rows[0].get("value", ""))
    except Exception as exc:
        log.debug("db fallback failed for %s: %s", key, exc)
        with _lock:
            _stats["errors"] += 1
    return None


def _db_get_all():
    """Fetch all fleet_config rows."""
    try:
        import db
        return db.select("fleet_config", {"select": "key,value"}) or []
    except Exception as exc:
        log.debug("db full fetch failed: %s", exc)
        with _lock:
            _stats["errors"] += 1
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_config(key, default=None):
    """Get a config value. Reads from cache first, falls back to DB.

    When realtime is connected, cache entries are kept fresh by incoming
    events and never expire. When realtime is down, entries expire after
    CACHE_TTL_S seconds and are re-fetched from the database.
    """
    value, hit = _cache_get(key)
    if hit:
        return value

    with _lock:
        _stats["cache_misses"] += 1

    # Cache miss — query DB
    value = _db_get(key)
    if value is not None:
        _cache_set(key, value)
        with _lock:
            _stats["db_fallbacks"] += 1
        return value

    return default


def get_all_config():
    """Return a dict of all cached config key-value pairs.

    If the cache is empty, performs a full DB fetch first.
    """
    with _lock:
        if _cache:
            return {k: v for k, (v, _ts) in _cache.items()}

    rows = _db_get_all()
    if rows:
        _cache_bulk_load(rows)
        return {r["key"]: str(r.get("value", "")) for r in rows if r.get("key")}
    return {}


def invalidate(key=None):
    """Drop one key or the entire cache, forcing the next read to hit DB."""
    with _lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)


# ---------------------------------------------------------------------------
# Realtime listener
# ---------------------------------------------------------------------------
def _handle_realtime_event(event_type, record):
    """Process a single realtime change event."""
    with _lock:
        _stats["rt_events"] += 1

    key = record.get("key")
    if not key:
        return

    if event_type in ("INSERT", "UPDATE"):
        value = record.get("value")
        if value is not None:
            _cache_set(key, str(value))
            log.debug("rt %s: %s", event_type.lower(), key)
    elif event_type == "DELETE":
        _cache_delete(key)
        log.debug("rt delete: %s", key)


def _realtime_listen():
    """Background thread: subscribe to fleet_config changes via Supabase Realtime.

    Uses the Supabase Realtime HTTP/WebSocket protocol. Falls back gracefully
    if the websocket library is not available or the connection fails.
    """
    global _realtime_connected
    delay = RECONNECT_DELAY_S

    # Pre-populate cache on startup
    rows = _db_get_all()
    if rows:
        _cache_bulk_load(rows)

    while not _stop_event.is_set():
        try:
            _connect_and_listen()
            delay = RECONNECT_DELAY_S  # reset on clean disconnect
        except Exception as exc:
            log.debug("realtime connection error: %s", exc)
            with _lock:
                _realtime_connected = False
                _stats["errors"] += 1
        finally:
            with _lock:
                _realtime_connected = False

        if _stop_event.is_set():
            break

        # Exponential backoff with cap
        log.debug("realtime reconnecting in %.0fs", delay)
        _stop_event.wait(timeout=delay)
        delay = min(delay * 2, MAX_RECONNECT_DELAY_S)


def _connect_and_listen():
    """Establish a Supabase Realtime websocket connection and listen for changes.

    Protocol: Supabase Realtime uses Phoenix channels over WebSocket.
    Endpoint: wss://<project>.supabase.co/realtime/v1/websocket?apikey=<key>
    """
    global _realtime_connected

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log.debug("realtime: SUPABASE_URL or SUPABASE_SERVICE_KEY not set, sleeping")
        _stop_event.wait(timeout=MAX_RECONNECT_DELAY_S)
        return

    try:
        import websocket  # websocket-client
    except ImportError:
        log.debug("realtime: websocket-client not installed, using poll-only mode")
        _poll_fallback()
        return

    # Build the realtime websocket URL
    ws_url = url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = ws_url + "/realtime/v1/websocket?apikey=" + key + "&vsn=1.0.0"

    ws = websocket.WebSocket()
    ws.settimeout(30)

    try:
        ws.connect(ws_url)

        # Join the realtime channel for fleet_config
        join_msg = json.dumps({
            "topic": "realtime:public:fleet_config",
            "event": "phx_join",
            "payload": {"config": {
                "broadcast": {"self": False},
                "presence": {"key": ""},
                "postgres_changes": [{
                    "event": "*",
                    "schema": "public",
                    "table": "fleet_config",
                }],
            }},
            "ref": "1",
        })
        ws.send(join_msg)

        with _lock:
            _realtime_connected = True
        log.info("realtime: connected to fleet_config channel")

        # Heartbeat tracking
        last_heartbeat = time.time()
        heartbeat_interval = 30

        while not _stop_event.is_set():
            # Send heartbeat
            now = time.time()
            if now - last_heartbeat >= heartbeat_interval:
                hb = json.dumps({
                    "topic": "phoenix",
                    "event": "heartbeat",
                    "payload": {},
                    "ref": str(int(now)),
                })
                try:
                    ws.send(hb)
                except Exception:
                    break
                last_heartbeat = now

            # Receive with timeout so we can check _stop_event
            try:
                ws.settimeout(5)
                raw = ws.recv()
            except Exception:
                # Timeout or connection error
                try:
                    # Check if it was just a timeout
                    if ws.connected:
                        continue
                except Exception:
                    pass
                break

            if not raw:
                continue

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            event = msg.get("event", "")
            payload = msg.get("payload", {})

            if event == "postgres_changes":
                data = payload.get("data", payload)
                event_type = data.get("type", "").upper()
                record = data.get("record", {})
                if event_type and record:
                    _handle_realtime_event(event_type, record)
            elif event == "phx_reply":
                status = payload.get("status")
                if status == "error":
                    log.warning("realtime: channel join error: %s", payload)
                    break
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _poll_fallback():
    """When websocket is unavailable, poll the DB periodically."""
    log.info("realtime: using poll fallback (interval=%ds)", int(CACHE_TTL_S))
    while not _stop_event.is_set():
        _stop_event.wait(timeout=CACHE_TTL_S)
        if _stop_event.is_set():
            break
        rows = _db_get_all()
        if rows:
            _cache_bulk_load(rows)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def start():
    """Start the realtime listener in a background daemon thread."""
    global _listener_thread
    with _lock:
        if _listener_thread is not None and _listener_thread.is_alive():
            return
    _stop_event.clear()
    _listener_thread = threading.Thread(
        target=_realtime_listen, name="config-sync-rt", daemon=True
    )
    _listener_thread.start()
    log.debug("realtime listener started")


def stop():
    """Stop the realtime listener and clear connection state."""
    global _listener_thread, _realtime_connected
    _stop_event.set()
    with _lock:
        _realtime_connected = False
    if _listener_thread is not None:
        _listener_thread.join(timeout=10)
        _listener_thread = None
    log.debug("realtime listener stopped")


def is_connected():
    """Check whether the realtime subscription is active."""
    with _lock:
        return _realtime_connected
