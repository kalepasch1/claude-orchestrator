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
    def _send_json(self, status, payload):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(payload, indent=2, default=str).encode())

    def do_GET(self):
        if self.path.startswith("/compliance/v1/"):
            from compliance_api_gateway import gateway
            params = {key: values[-1] for key, values in parse_qs(urlparse(self.path).query).items()}
            status, payload = gateway.dispatch("GET", self.path, params)
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
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict): raise ValueError("JSON object required")
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send_json(400, {"error": str(exc)})
        from compliance_api_gateway import gateway
        status, payload = gateway.dispatch("POST", self.path, body)
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
