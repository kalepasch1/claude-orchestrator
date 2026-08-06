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

# --- Prometheus gauge -------------------------------------------------------
# prometheus_client is OPTIONAL on purpose. This repo ships no dependency
# manifest, the module is not installed on the runner boxes, and canary.py is
# imported by the scheduler — so a bare `from prometheus_client import Gauge`
# would make the whole module unimportable everywhere it currently works. That
# is the failure mode the earlier attempt at this hit.
#
# So: use the real client when present, otherwise a minimal shim exposing the
# same surface the canary uses (set/inc/dec/get + text rendering). Either way
# `canary.canary_last_success` exists at module level and `/metrics` reports it,
# which is the behavior callers depend on. Uses a private CollectorRegistry
# rather than the global default so re-import under test cannot raise
# Duplicated timeseries.
_GAUGE_NAME = "canary_last_success"
_GAUGE_DOC = "Indicator of the last validation result (1 for success, 0 for failure)"


class _FallbackGauge:
    """Prometheus-Gauge-shaped stand-in used when prometheus_client is absent."""

    def __init__(self, name, documentation):
        self._name = name
        self._documentation = documentation
        self._value = 0.0
        self._lock = threading.Lock()

    def set(self, value):
        with self._lock:
            self._value = float(value)

    def inc(self, amount=1):
        with self._lock:
            self._value += float(amount)

    def dec(self, amount=1):
        with self._lock:
            self._value -= float(amount)

    def get(self):
        with self._lock:
            return self._value

    def render(self):
        return (f"# HELP {self._name} {self._documentation}\n"
                f"# TYPE {self._name} gauge\n"
                f"{self._name} {self.get()}\n")


try:  # pragma: no cover - depends on the host environment
    from prometheus_client import CollectorRegistry, Gauge, generate_latest

    PROMETHEUS_AVAILABLE = True
    CANARY_REGISTRY = CollectorRegistry()
    canary_last_success = Gauge(_GAUGE_NAME, _GAUGE_DOC, registry=CANARY_REGISTRY)
except Exception:  # ImportError, or a client version without these names
    PROMETHEUS_AVAILABLE = False
    CANARY_REGISTRY = None
    generate_latest = None
    canary_last_success = _FallbackGauge(_GAUGE_NAME, _GAUGE_DOC)


def _render_metrics():
    """Render the canary metrics exposition text. Never raises."""
    try:
        if PROMETHEUS_AVAILABLE and generate_latest is not None:
            return generate_latest(CANARY_REGISTRY).decode("utf-8")
        return canary_last_success.render()
    except Exception:
        return f"# {_GAUGE_NAME} unavailable\n"


def _record_verdict(verdict):
    """Mirror a verdict onto the gauge. Metrics must never break the canary."""
    try:
        canary_last_success.set(1 if verdict == "promote" else 0)
    except Exception:
        pass


def evaluate(metrics_url=None):
    metrics_url = metrics_url or os.environ.get("METRICS_URL")
    if not metrics_url:
        _record_verdict("promote")
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
        _record_verdict("rollback")
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
    verdict = "rollback" if fails else "promote"
    _record_verdict(verdict)
    return {"verdict": verdict,
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
            body = ("canary_up 1\n" + _render_metrics()).encode("utf-8")
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

