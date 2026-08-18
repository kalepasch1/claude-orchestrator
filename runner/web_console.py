"""
web_console.py — lightweight HTTP endpoint for live run monitoring.

Serves a JSON snapshot of the current task queue, running tasks, and key metrics.
Designed to be polled by a simple dashboard or browser tab.
"""
import os, sys, json, logging, http.server, threading, time
from urllib.parse import parse_qs, urlparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)

PORT = int(os.environ.get("ORCH_CONSOLE_PORT", "8701"))

_snapshot_cache = {"data": {}, "ts": 0.0}


def _build_snapshot():
    """Build a live snapshot of the orchestrator state."""
    now = time.time()
    if now - _snapshot_cache["ts"] < 10:
        return _snapshot_cache["data"]

    import db
    states = {}
    for state in ("QUEUED", "RUNNING", "DONE", "MERGED", "BLOCKED", "TESTFAIL", "BUILDFAIL"):
        try:
            states[state] = db.count("tasks", {"state": f"eq.{state}"}) or 0
        except Exception:
            states[state] = 0

    running = []
    try:
        rows = db.select("tasks", {
            "select": "id,slug,account,project_id,updated_at",
            "state": "eq.RUNNING",
            "order": "updated_at.asc",
            "limit": "20",
        }) or []
        running = [{"slug": r.get("slug"), "account": r.get("account"),
                     "project_id": r.get("project_id"), "updated_at": r.get("updated_at")}
                    for r in rows]
    except Exception:
        pass

    recent_done = []
    try:
        rows = db.select("tasks", {
            "select": "slug,state,updated_at",
            "state": "in.(DONE,MERGED)",
            "order": "updated_at.desc",
            "limit": "10",
        }) or []
        recent_done = [{"slug": r.get("slug"), "state": r.get("state"),
                        "updated_at": r.get("updated_at")} for r in rows]
    except Exception:
        pass

    snapshot = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "queue_states": states,
        "running_tasks": running,
        "recent_completions": recent_done,
        "total_queued": states.get("QUEUED", 0),
        "total_running": states.get("RUNNING", 0),
        "total_blocked": states.get("BLOCKED", 0) + states.get("TESTFAIL", 0) + states.get("BUILDFAIL", 0),
    }
    _snapshot_cache["data"] = snapshot
    _snapshot_cache["ts"] = now
    return snapshot


class ConsoleHandler(http.server.BaseHTTPRequestHandler):
    def _send_json(self, status, payload, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for header, value in (extra_headers or {}).items():
            self.send_header(header, value)
        # `Access-Control-Allow-Origin: *` used to go out on every response.
        # On a loopback service that hands any web page the whole compliance
        # surface, so only an explicitly configured origin is echoed now.
        try:
            import compliance_auth
            for header, value in compliance_auth.cors_headers(self.headers.get("Origin")).items():
                self.send_header(header, value)
        except Exception:
            pass
        self.end_headers()
        self.wfile.write(json.dumps(payload, indent=2, default=str).encode())

    def _caller(self):
        """Bearer token (if presented) and the peer address, for auth."""
        token = None
        header = self.headers.get("Authorization") or ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
        token = token or self.headers.get("X-Compliance-Token")
        try:
            client_host = self.client_address[0]
        except (AttributeError, IndexError, TypeError):
            client_host = None
        return token, client_host

    def do_GET(self):
        if self.path.startswith("/compliance/v1/"):
            from compliance_api_gateway import gateway
            params = {key: values[-1] for key, values in parse_qs(urlparse(self.path).query).items()}
            token, client_host = self._caller()
            status, payload = gateway.dispatch("GET", self.path, params,
                                               client_host=client_host, token=token)
            return self._send_json(status, payload)
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})

        if self.path in ("/", "/snapshot"):
            try:
                snapshot = _build_snapshot()
                self._send_json(200, snapshot)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/compliance/v1/"):
            return self._send_json(404, {"error": "not found"})
        import compliance_auth
        try:
            length = int(self.headers.get("Content-Length", "0"))
            # Bound BEFORE reading. The previous code read Content-Length bytes
            # unconditionally, so a single declared-huge request could exhaust
            # memory on the loopback console.
            compliance_auth.check_body_size(length)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict): raise ValueError("JSON object required")
        except compliance_auth.AuthError as exc:
            # The oversized body is deliberately never read, so the connection
            # cannot be reused — say so rather than leaving the peer to
            # discover it as a reset mid-response.
            self.close_connection = True
            return self._send_json(exc.status, {"error": str(exc)},
                                   extra_headers={"Connection": "close"})
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send_json(400, {"error": str(exc)})
        from compliance_api_gateway import gateway
        token, client_host = self._caller()
        status, payload = gateway.dispatch("POST", self.path, body,
                                           client_host=client_host, token=token)
        self._send_json(status, payload)

    def log_message(self, format, *args):
        pass  # suppress request logging


def start_console(port=None, daemon=True):
    """Start the console HTTP server in a background thread."""
    p = port or PORT
    server = http.server.HTTPServer(("127.0.0.1", p), ConsoleHandler)
    t = threading.Thread(target=server.serve_forever, daemon=daemon)
    t.start()
    log.info("web_console: listening on http://127.0.0.1:%d", p)
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"Starting console on http://127.0.0.1:{PORT}")
    server = start_console(daemon=False)
