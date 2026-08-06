#!/usr/bin/env python3
"""
canary.py - metric-gated deploys. After a deploy, compare REAL metrics (error rate, p95,
conversion) from a JSON metrics endpoint against thresholds; promote if healthy, signal
rollback if a metric regressed. Used by the overnight deploy window instead of a bare 200.

METRICS_URL must return JSON like {"error_rate":0.4,"p95_ms":180,"conversion":3.1}.
Thresholds via env: CANARY_MAX_ERROR_RATE, CANARY_MAX_P95_MS, CANARY_MIN_CONVERSION.
"""
import os, sys, json, threading, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# RESTORED 2026-08-02: merge c502818b 'Merge branch 'agent/canary-gemini-25-...'
# (auto-resolved)' dropped the `threading` / `http.server` imports and these two module
# globals while KEEPING every line that uses them, and stranded the whole metrics block
# below the `if __name__` entrypoint. The result imported fine and raised NameError the
# moment start_metrics_server() was called — the crash-free-until-used class the
# regression guard now blocks. Original shape restored from d1530ed0.
_metrics_server = None
_metrics_server_lock = threading.Lock()


def validate_canary(value):
    """True when the input mentions a canary (case-insensitive substring).

    Tiny input validator for canary-tagged payloads/labels; fail-soft on
    non-string input (returns False rather than raising).
    """
    if not isinstance(value, str):
        return False
    return "canary" in value.lower()


def evaluate(metrics_url=None):
    metrics_url = metrics_url or os.environ.get("METRICS_URL")
    if not metrics_url:
        return {"verdict": "promote", "reason": "no metrics endpoint configured"}
    retries = int(os.environ.get("CANARY_FETCH_RETRIES", "2"))
    last_err = None
    for attempt in range(1 + retries):
        try:
            with urllib.request.urlopen(metrics_url, timeout=10) as r:
                m = json.loads(r.read().decode())
            break
        except Exception as e:
            last_err = e
            if attempt < retries:
                import time
                time.sleep(min(2 ** attempt, 8))
    else:
        return {"verdict": "rollback", "reason": f"metrics unreachable after {1 + retries} attempts ({last_err})"}
    fails = []
    def bad(key, val, limit, cmp):
        if limit is None or val is None:
            return
        if (cmp == "max" and val > limit) or (cmp == "min" and val < limit):
            fails.append(f"{key}={val} breaches {cmp} {limit}")
    bad("error_rate", m.get("error_rate"), _f("CANARY_MAX_ERROR_RATE"), "max")
    bad("p95_ms", m.get("p95_ms"), _f("CANARY_MAX_P95_MS"), "max")
    bad("conversion", m.get("conversion"), _f("CANARY_MIN_CONVERSION"), "min")
    return {"verdict": "rollback" if fails else "promote",
            "reason": "; ".join(fails) or "all metrics within thresholds", "metrics": m}


def _f(k):
    # parse optional float threshold from env; returns None if unset so the check is skipped
    v = os.environ.get(k)
    return float(v) if v not in (None, "") else None


def main(argv=None):
    """CLI entrypoint: print the evaluation as JSON and return an exit code.

    Exit 0 on 'promote', 1 on 'rollback', so shell callers can gate a deploy
    on the verdict without parsing stdout.
    """
    argv = sys.argv[1:] if argv is None else argv
    result = evaluate(argv[0] if argv else None)
    print(json.dumps(result))
    return 0 if result.get("verdict") == "promote" else 1


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
    sys.exit(main())

