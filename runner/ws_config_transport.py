#!/usr/bin/env python3
"""
ws_config_transport.py — WebSocket transport foundation for real-time config.

Provides a WebSocket-based transport layer that can replace or augment the
polling-based realtime_config_sync. When a Supabase Realtime channel is
available, config changes are pushed instantly; otherwise falls back to
the existing polling loop.

Sub-task 1/5 of upgrade-to-real-time-configuration-management.

Usage:
    from ws_config_transport import WSConfigTransport
    transport = WSConfigTransport()
    transport.start()              # connect and listen
    transport.on_change(callback)  # register change handler
    transport.stop()               # disconnect
"""
import os
import sys
import json
import time
import threading
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger("ws_config_transport")

# Environment knobs
_WS_ENABLED = os.environ.get("ORCH_WS_CONFIG", "true").lower() == "true"
_RECONNECT_DELAY = float(os.environ.get("ORCH_WS_RECONNECT_DELAY", "5"))
_MAX_RECONNECT_DELAY = float(os.environ.get("ORCH_WS_MAX_RECONNECT_DELAY", "60"))
_HEARTBEAT_INTERVAL = float(os.environ.get("ORCH_WS_HEARTBEAT_INTERVAL", "30"))


class WSConfigTransport:
    """WebSocket transport for fleet_config change notifications.

    Connects to the Supabase Realtime channel for the fleet_config table
    and dispatches change events to registered callbacks. Includes
    automatic reconnection with exponential backoff.
    """

    def __init__(self, supabase_url=None, supabase_key=None):
        self._url = supabase_url or os.environ.get("SUPABASE_URL", "")
        self._key = supabase_key or os.environ.get("SUPABASE_ANON_KEY", "")
        self._callbacks = []
        self._thread = None
        self._running = False
        self._connected = False
        self._lock = threading.Lock()
        self._reconnect_delay = _RECONNECT_DELAY
        self._stats = {
            "connects": 0,
            "disconnects": 0,
            "messages_received": 0,
            "errors": 0,
            "last_message_ts": 0.0,
        }

    def on_change(self, callback):
        """Register a callback for config changes: callback(key, value, old_value)."""
        self._callbacks.append(callback)

    def start(self):
        """Start the WebSocket listener in a background thread."""
        if not _WS_ENABLED:
            log.info("WebSocket config transport disabled via ORCH_WS_CONFIG")
            return
        if not self._url or not self._key:
            log.warning("Missing SUPABASE_URL or SUPABASE_ANON_KEY; WS transport inactive")
            return
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, name="ws-config-transport", daemon=True
        )
        self._thread.start()
        log.info("WebSocket config transport started")

    def stop(self):
        """Stop the WebSocket listener."""
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        log.info("WebSocket config transport stopped")

    def stats(self):
        """Return transport statistics."""
        return {**self._stats, "connected": self._connected, "running": self._running}

    def _run_loop(self):
        """Main reconnection loop — connects, listens, reconnects on failure."""
        while self._running:
            try:
                self._connect_and_listen()
            except Exception as exc:
                self._stats["errors"] += 1
                log.warning("WS transport error: %s; reconnecting in %.0fs", exc, self._reconnect_delay)
                self._connected = False
                self._stats["disconnects"] += 1
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, _MAX_RECONNECT_DELAY)

    def _connect_and_listen(self):
        """Establish WebSocket connection and listen for config changes.

        Uses the Supabase Realtime protocol: connect to the /realtime/v1/websocket
        endpoint, join the 'realtime:fleet_config' channel, and process INSERT/UPDATE
        events. Falls back gracefully if websocket-client is not installed.
        """
        try:
            import websocket  # websocket-client package
        except ImportError:
            log.info("websocket-client not installed; WS transport dormant (pip install websocket-client)")
            self._running = False
            return

        ws_url = self._url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/realtime/v1/websocket?apikey={self._key}&vsn=1.0.0"

        ws = websocket.WebSocketApp(
            ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        ws.run_forever(ping_interval=_HEARTBEAT_INTERVAL, ping_timeout=10)

    def _on_open(self, ws):
        """Join the fleet_config realtime channel on connection."""
        self._connected = True
        self._reconnect_delay = _RECONNECT_DELAY
        self._stats["connects"] += 1
        join_msg = json.dumps({
            "topic": "realtime:public:fleet_config",
            "event": "phx_join",
            "payload": {"config": {"postgres_changes": [
                {"event": "*", "schema": "public", "table": "fleet_config"}
            ]}},
            "ref": str(int(time.time())),
        })
        ws.send(join_msg)
        log.info("WebSocket connected and joined fleet_config channel")

    def _on_message(self, ws, message):
        """Process incoming realtime messages."""
        try:
            msg = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return
        event = msg.get("event", "")
        if event in ("INSERT", "UPDATE", "postgres_changes"):
            payload = msg.get("payload", {})
            record = payload.get("record", payload.get("new", {}))
            old = payload.get("old_record", payload.get("old", {}))
            key = record.get("key", "")
            value = record.get("value")
            old_value = old.get("value") if old else None
            if key:
                self._stats["messages_received"] += 1
                self._stats["last_message_ts"] = time.time()
                self._dispatch(key, value, old_value)

    def _on_error(self, ws, error):
        log.debug("WS error: %s", error)

    def _on_close(self, ws, close_status_code, close_msg):
        self._connected = False
        log.debug("WS closed: %s %s", close_status_code, close_msg)

    def _dispatch(self, key, value, old_value):
        """Notify all registered callbacks of a config change."""
        for cb in self._callbacks:
            try:
                cb(key, value, old_value)
            except Exception as exc:
                log.warning("Callback error for key=%s: %s", key, exc)


# Module-level singleton for convenient import
_default_transport = None
_init_lock = threading.Lock()


def get_transport():
    """Get or create the module-level WSConfigTransport singleton."""
    global _default_transport
    if _default_transport is None:
        with _init_lock:
            if _default_transport is None:
                _default_transport = WSConfigTransport()
    return _default_transport
