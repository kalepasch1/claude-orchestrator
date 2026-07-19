#!/usr/bin/env python3
"""
canary.py - metric-gated deploys. After a deploy, compare REAL metrics (error rate, p95,
conversion) from a JSON metrics endpoint against thresholds; promote if healthy, signal
rollback if a metric regressed. Used by the overnight deploy window instead of a bare 200.

METRICS_URL must return JSON like {"error_rate":0.4,"p95_ms":180,"conversion":3.1}.
Thresholds via env: CANARY_MAX_ERROR_RATE, CANARY_MAX_P95_MS, CANARY_MIN_CONVERSION.
"""
import os, sys, json, urllib.request


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
    v = os.environ.get(k)
    return float(v) if v not in (None, "") else None


if __name__ == "__main__":
    print(evaluate(sys.argv[1] if len(sys.argv) > 1 else None))
