import os, sys, json, threading, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

_metrics_server = None
_metrics_server_lock = threading.Lock()

class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = b"canary_up 1\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def _not_found(self):
        self.send_error(404)

    do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_found

    def log_message(self, format, *args):
        pass  # keep canary stdout/stderr clean for the deploy window logs

def start_metrics_server():
    """Serve GET /metrics on 0.0.0.0:${CANARY_METRICS_PORT:-8000} in a daemon thread.

    Idempotent: subsequent calls return the already-running server. Fail-soft:
    any bind/startup error (port in use, bad port value) logs a warning and
    returns None so the canary is never wedged by its own metrics endpoint.
    """
    global _metrics_server
    with _metrics_server_lock:
        if _metrics_server is not None:
            return _metrics_server
        try:
            port = int(os.environ.get("CANARY_METRICS_PORT", "8000"))
            server = HTTPServer(("0.0.0.0", port), _MetricsHandler)
        except Exception as e:
            print(f"canary: metrics server not started: {e}", file=sys.stderr)
            return None
        threading.Thread(target=server.serve_forever, name="canary-metrics",
                         daemon=True).start()
        _metrics_server = server
        return server

if __name__ == "__main__":
    start_metrics_server()
