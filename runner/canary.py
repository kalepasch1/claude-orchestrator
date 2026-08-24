#!/usr/bin/env python3
"""
canary.py - metric-gated deploys. After a deploy, compare REAL metrics (error rate, p95,
conversion) from a JSON metrics endpoint against thresholds; promote if healthy, signal
rollback if a metric regressed. Used by the overnight deploy window instead of a bare 200.

METRICS_URL must return JSON like {"error_rate":0.4,"p95_ms":180,"conversion":3.1}.
Thresholds via env: CANARY_MAX_ERROR_RATE, CANARY_MAX_P95_MS, CANARY_MIN_CONVERSION.
"""
import os, sys, json, logging, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# RESTORED 2026-08-12: `validate_canary` referenced `_log` and the module never
# imported logging or bound `_log` — a NameError that only fired the first time
# validate_canary() was called. Same crash-free-until-used class as the
# _metrics_server regression noted below. Bind the logger next to the imports.
_log = logging.getLogger(__name__)

# RESTORED 2026-08-02: merge c502818b 'Merge branch 'agent/canary-gemini-25-...'
# (auto-resolved)' dropped the `threading` / `http.server` imports and these two module
# globals while KEEPING every line that uses them, and stranded the whole metrics block
# below the `if __name__` entrypoint. The result imported fine and raised NameError the
# moment start_metrics_server() was called — the crash-free-until-used class the
# regression guard now blocks. Original shape restored from d1530ed0.
_metrics_server = None
_metrics_server_lock = threading.Lock()

# Prometheus gauge: unix seconds of the last successful (promote) evaluation;
# 0 = never succeeded since process start. Implemented with stdlib only —
# prometheus_client is not a repo dependency, and /metrics already speaks the
# Prometheus text exposition format, so a hard import would add a dep for no
# behavior. The gauge state is module-level and lock-guarded.


class Gauge:
    """Minimal Prometheus-compatible gauge: set/inc/dec/get, stdlib only.

    Deliberately duck-types prometheus_client.Gauge rather than importing it —
    prometheus_client is not a repo dependency and render_metrics() already
    emits the Prometheus text exposition format. Fail-soft: a non-numeric value
    is ignored rather than raising, so a bad caller never wedges the canary.
    """

    def __init__(self, name, documentation=""):
        self.name = name
        self.documentation = documentation
        self._value = 0.0
        self._lock = threading.Lock()

    def set(self, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        with self._lock:
            self._value = v

    def inc(self, amount=1.0):
        try:
            delta = float(amount)
        except (TypeError, ValueError):
            return
        with self._lock:
            self._value += delta

    def dec(self, amount=1.0):
        self.inc(-amount if isinstance(amount, (int, float)) else amount)

    def get(self):
        with self._lock:
            return self._value

    def __repr__(self):
        return f"Gauge({self.name!r}, {self.get()!r})"


# Module-level gauge object — `canary.canary_last_success` is part of the public
# surface. Value is the unix timestamp of the last promote (0.0 = never), which
# doubles as the success/failure indicator: non-zero means the last validation
# succeeded, 0 means it has not.
canary_last_success = Gauge(
    "canary_last_success",
    "Indicator of the last validation result (1 for success, 0 for failure)",
)

_gauges = {"canary_last_success": canary_last_success}
_gauges_lock = threading.Lock()


def set_gauge(name, value):
    """Set a gauge value. Fail-soft: unknown names are created, bad values ignored."""
    with _gauges_lock:
        gauge = _gauges.get(name)
        if gauge is None:
            gauge = _gauges[name] = Gauge(name)
    gauge.set(value)


def get_gauge(name):
    """Current gauge value (0.0 for unknown gauges)."""
    with _gauges_lock:
        gauge = _gauges.get(name)
    return gauge.get() if gauge is not None else 0.0


def record_success(ts=None):
    """Mark a successful canary evaluation on the canary_last_success gauge."""
    set_gauge("canary_last_success", time.time() if ts is None else ts)


def record_failure():
    """Reset canary_last_success to 0 when an evaluation fails.

    Only the promote path ever touched this gauge, so after a rollback the
    gauge kept the timestamp of the *previous* success. Any alert written as
    `time() - canary_last_success > threshold` therefore stayed green through
    a failing canary until the threshold expired on its own -- the gauge said
    "last succeeded 40s ago" while the canary was actively rolling back.
    Zeroing on failure makes the same alert fire immediately, and matches the
    documented contract that 0 means "not currently succeeding".
    """
    set_gauge("canary_last_success", 0)


#: How stale `canary_last_success` may get before the heartbeat counts as expired.
#: Read at call time, not import time, so an operator can widen it during a long
#: deploy window without restarting the canary process.
HEARTBEAT_MAX_AGE_DEFAULT_S = 300.0


def _heartbeat_max_age():
    try:
        value = float(os.environ.get("CANARY_HEARTBEAT_MAX_AGE_S", HEARTBEAT_MAX_AGE_DEFAULT_S))
    except (TypeError, ValueError):
        return HEARTBEAT_MAX_AGE_DEFAULT_S
    return value if value > 0 else HEARTBEAT_MAX_AGE_DEFAULT_S


def heartbeat_age(now=None):
    """Seconds since the last successful evaluation, or None if there has never been one.

    None and 0 are different answers and the caller needs both: 0 is the gauge's documented
    "not currently succeeding" sentinel (record_failure sets it), while None means the
    process has not yet completed a first evaluation.
    """
    last = get_gauge("canary_last_success")
    if not last:
        return None
    return max(0.0, (time.time() if now is None else now) - last)


def heartbeat_expired(now=None, max_age=None):
    """True when the canary heartbeat is stale (or has never beaten).

    The gauge has always been *written* — record_success stamps it, record_failure zeroes it
    — but nothing in this module ever READ it back, so a canary that stopped evaluating
    entirely (crashed thread, wedged deploy window, host asleep) looked exactly like a canary
    that was fine: /metrics kept serving the last timestamp it happened to have, and the
    staleness arithmetic was left to whatever external alert someone remembered to write.

    A never-beating heartbeat is expired. That is the case that matters most — a canary that
    dies before its first success is the one nobody notices.
    """
    age = heartbeat_age(now=now)
    if age is None:
        return True
    return age > (_heartbeat_max_age() if max_age is None else max_age)


def heartbeat_status(now=None):
    """Structured heartbeat verdict, shaped like evaluate()'s so callers can treat them alike."""
    age = heartbeat_age(now=now)
    max_age = _heartbeat_max_age()
    if age is None:
        return {"expired": True, "age_s": None, "max_age_s": max_age,
                "reason": "no successful canary evaluation since process start"}
    if age > max_age:
        return {"expired": True, "age_s": round(age, 3), "max_age_s": max_age,
                "reason": f"last success was {age:.0f}s ago, over the {max_age:.0f}s limit"}
    return {"expired": False, "age_s": round(age, 3), "max_age_s": max_age,
            "reason": "heartbeat is current"}


def render_metrics():
    """Prometheus text exposition for GET /metrics.

    canary_heartbeat_expired is computed at scrape time rather than stored: staleness is a
    function of the clock, so a gauge only written on state change would go on reporting 0
    for exactly the failure it exists to catch — a canary that has stopped writing anything.
    """
    set_gauge("canary_heartbeat_expired", 1 if heartbeat_expired() else 0)
    lines = ["canary_up 1"]
    with _gauges_lock:
        gauges = [_gauges[name] for name in sorted(_gauges)]
    for gauge in gauges:
        if gauge.documentation:
            lines.append(f"# HELP {gauge.name} {gauge.documentation}")
        lines.append(f"# TYPE {gauge.name} gauge")
        lines.append(f"{gauge.name} {gauge.get()}")
    return ("\n".join(lines) + "\n").encode()


def validate_canary(response_text):
    """True when response_text carries a canary marker. Delegates — see below.

    UNIFIED 2026-08-13: there were three copies of this function and they did not
    agree. Root canary.py and runner/canary_validation.py both match on a WORD
    BOUNDARY (`\\bcanary\\b`); this one matched on a SUBSTRING
    (`"canary" in text.lower()`). So "precanary" and "canaryX" validated here and
    failed at the other two entry points.

    That is the worst possible shape for a marker check: its whole job is to
    confirm a canary survived a pipeline hop, and it returned a different verdict
    depending on which import path the caller happened to use — a hop could be
    reported as both intact and broken. Neither answer was flagged, because each
    copy was self-consistent and no test compared them.

    Word boundary wins: it is what two of the three implementations already did and
    what root canary.py documents ("Mirrors runner/canary_validation.py"). Rather
    than a fourth copy of the regex, delegate, so the semantics can only ever be
    changed in one place.

    Logging stays here (INFO on hit, WARNING on miss) because callers of this module
    depend on this logger's name.
    """
    if not isinstance(response_text, str):
        _log.warning("canary marker not found: non-string input (%s)", type(response_text).__name__)
        record_failure()
        return False
    import canary_validation
    if canary_validation.validate_canary(response_text):
        _log.info("canary marker found in response text")
        return True
    # VALIDATION FAILURE PATH. Zeroing here, not only in main(): a missing marker means
    # the canary did NOT survive the pipeline hop, but the gauge kept the timestamp of
    # the last success, so an alert written as
    # `time() - canary_last_success > threshold` stayed green through a failing
    # validation until the threshold expired on its own. That is the same defect
    # record_failure was written for on the rollback path, left open on this one.
    #
    # This module owns the gauge and this function already logs, so the side effect is
    # where it belongs; `canary_validation.validate_canary` stays a pure predicate.
    _log.warning("canary marker NOT found in response text")
    record_failure()
    return False


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

    # `--heartbeat` reports staleness WITHOUT evaluating: the whole point is to answer
    # "is this canary still beating" from outside, at a moment when running an evaluation
    # is exactly what may be wedged. Exit 1 when expired, matching the rollback convention.
    if argv and argv[0] == "--heartbeat":
        status = heartbeat_status()
        print(json.dumps(status))
        return 1 if status["expired"] else 0

    # SETUP: actually start the metrics endpoint.
    #
    # `start_metrics_server()` has been implemented, idempotent, fail-soft and covered by
    # 12 tests for some time — and called from nowhere. `grep -rn start_metrics_server`
    # across runner/ and scripts/ returns only its own definition. So the gauge below was
    # faithfully updated on every run and no scraper could ever read it: the module
    # docstring advertises a /metrics endpoint that never bound a port.
    #
    # Opt-in, because binding a port is not free: this CLI also runs inside CI and inside
    # the deploy window, where a stray listener (or a port collision with a parallel
    # canary) would be a new failure mode for a tool whose entire job is to not be one.
    # Off by default preserves today's behaviour exactly.
    if os.environ.get("CANARY_METRICS_ENABLED", "false").strip().lower() == "true":
        # Before evaluate(), so a long metrics fetch is still scrapeable while it runs;
        # start_metrics_server returns immediately (daemon thread) and returns None
        # rather than raising if the port is taken.
        start_metrics_server()

    try:
        result = evaluate(argv[0] if argv else None)
    except Exception as exc:
        # EXCEPTION PATH. evaluate() returns a rollback verdict for the failures it
        # anticipates, but anything it does NOT anticipate propagated straight out of
        # main() — so the gauge kept the previous SUCCESS timestamp while the canary was
        # crashing, and a `time() - canary_last_success > threshold` alert read green.
        # A canary that raises is not succeeding; the gauge has to say so, and it has to
        # say so before the traceback escapes.
        record_failure()
        result = {"verdict": "rollback", "reason": f"canary evaluation raised: {exc}"}
        _log.exception("canary evaluation raised; gauge zeroed and verdict forced to rollback")
        print(json.dumps(result))
        return 1

    if result.get("verdict") == "promote":
        record_success()
    else:
        # Failure check location: a rollback must clear the gauge, not leave
        # the previous success timestamp standing.
        record_failure()
    print(json.dumps(result))
    return 0 if result.get("verdict") == "promote" else 1


class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = render_metrics()
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
    # Configure logging only when run as a CLI (a module-level basicConfig
    # would hijack the root logger for every runner that imports canary).
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    sys.exit(main())

