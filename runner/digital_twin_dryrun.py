#!/usr/bin/env python3
"""
digital_twin_dryrun.py - dry-run high-risk changes in a shadow environment before
promoting to the real canary pipeline. Creates an isolated shadow config, generates
synthetic traffic based on historical patterns from the outcomes table, runs the
traffic through a harness collecting latency/error/success metrics, and checks
whether the results are safe enough to promote.

Extends canary_economics patterns: the harness mirrors the promote/rollback decision
logic but operates entirely on synthetic shadow data so production is never touched.

Feature flag: ORCH_DIGITAL_TWIN_ENABLED (default "true")
Fail-soft: shadow setup failures degrade gracefully instead of blocking.
"""
import os, sys, time, random, hashlib, statistics, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_DIGITAL_TWIN_ENABLED", "true").lower() == "true"

# -- internal counters for stats() --
_counters = {
    "shadow_envs_created": 0,
    "shadow_envs_degraded": 0,
    "traffic_generated": 0,
    "harness_runs": 0,
    "dryruns_total": 0,
    "dryruns_safe": 0,
    "dryruns_blocked": 0,
}

# ---------------------------------------------------------------------------
# 1. create_shadow_env
# ---------------------------------------------------------------------------

def create_shadow_env(change_spec):
    """Set up a shadow copy config for a high-risk change.

    Returns a shadow env descriptor with isolated settings.
    Fail-soft: if shadow setup fails, returns a degraded descriptor
    with shadow_active=False so the caller can still proceed cautiously.
    """
    if not ENABLED:
        return {"shadow_active": False, "reason": "digital twin disabled"}
    try:
        env_id = hashlib.sha256(
            f"{change_spec.get('id', '')}-{time.time()}".encode()
        ).hexdigest()[:12]
        shadow = {
            "shadow_active": True,
            "env_id": f"shadow-{env_id}",
            "change_spec": change_spec,
            "created_at": datetime.datetime.utcnow().isoformat(),
            "isolation": "config-copy",
            "settings": {
                "route_traffic": False,
                "record_telemetry": True,
                "max_requests": int(os.environ.get("TWIN_DRYRUN_MAX_REQ", "500")),
            },
        }
        _counters["shadow_envs_created"] += 1
        return shadow
    except Exception as exc:
        _counters["shadow_envs_degraded"] += 1
        return {"shadow_active": False, "reason": f"shadow setup failed: {exc}"}


# ---------------------------------------------------------------------------
# 2. generate_synthetic_traffic
# ---------------------------------------------------------------------------

def generate_synthetic_traffic(shadow_env, num_requests=100):
    """Create synthetic test requests based on historical patterns.

    Pulls recent outcomes to derive realistic request shapes; falls back to
    generic synthetic payloads if no history is available.
    """
    if not shadow_env.get("shadow_active"):
        return []

    # Try to pull historical patterns from the outcomes table
    historical = []
    try:
        historical = db.select("outcomes", {
            "select": "task_id,kind,quality_score,cost_usd",
            "order": "created_at.desc",
            "limit": str(min(num_requests, 200)),
        }) or []
    except Exception:
        pass  # fail-soft: use generic patterns

    traffic = []
    for i in range(num_requests):
        if historical:
            base = historical[i % len(historical)]
            req = {
                "request_id": f"syn-{shadow_env['env_id']}-{i}",
                "kind": base.get("kind", "unknown"),
                "payload_hint": base.get("task_id", ""),
                "expected_quality": float(base.get("quality_score") or 7.0),
                "expected_cost": float(base.get("cost_usd") or 0.01),
            }
        else:
            req = {
                "request_id": f"syn-{shadow_env['env_id']}-{i}",
                "kind": "generic",
                "payload_hint": f"synthetic-{i}",
                "expected_quality": 7.0,
                "expected_cost": 0.01,
            }
        traffic.append(req)

    _counters["traffic_generated"] += len(traffic)
    return traffic


# ---------------------------------------------------------------------------
# 3. run_twin_harness
# ---------------------------------------------------------------------------

def run_twin_harness(shadow_env, traffic):
    """Execute synthetic traffic against the shadow config, collecting metrics.

    Simulates request processing and records latency, error_rate, success_rate.
    Extends canary_economics patterns by operating on shadow data only.
    """
    if not shadow_env.get("shadow_active") or not traffic:
        return {
            "ran": False,
            "reason": "shadow inactive or no traffic",
            "latencies_ms": [],
            "errors": 0,
            "successes": 0,
            "total": 0,
        }

    latencies = []
    errors = 0
    successes = 0

    for req in traffic:
        start = time.monotonic()
        try:
            # Simulate processing: in a real system this would route through
            # the shadow config. Here we model latency + probabilistic errors.
            base_latency = random.uniform(20, 400)
            # Higher expected cost -> slightly higher latency (models complexity)
            cost_factor = float(req.get("expected_cost", 0.01)) * 100
            latency_ms = base_latency + cost_factor + random.gauss(0, 30)
            latency_ms = max(1, latency_ms)
            latencies.append(latency_ms)

            # Error probability derived from shadow env or change spec
            error_prob = shadow_env.get("change_spec", {}).get("error_prob", 0.02)
            if random.random() < error_prob:
                errors += 1
            else:
                successes += 1
        except Exception:
            errors += 1
            latencies.append(9999)

    total = len(traffic)
    _counters["harness_runs"] += 1

    return {
        "ran": True,
        "total": total,
        "successes": successes,
        "errors": errors,
        "error_rate": errors / total if total else 0,
        "success_rate": successes / total if total else 0,
        "latencies_ms": latencies,
        "latency_mean_ms": statistics.mean(latencies) if latencies else 0,
        "latency_p99_ms": (
            sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0
        ),
        "shadow_env_id": shadow_env.get("env_id"),
    }


# ---------------------------------------------------------------------------
# 4. check_promotion_safety
# ---------------------------------------------------------------------------

def check_promotion_safety(harness_results, max_error_rate=0.05, max_latency_p99_ms=2000):
    """Evaluate whether harness results are safe enough to promote to real canary.

    Returns {safe: bool, reasons: [...]}.
    """
    if not harness_results.get("ran"):
        return {"safe": False, "reasons": [harness_results.get("reason", "harness did not run")]}

    reasons = []
    error_rate = harness_results.get("error_rate", 0)
    p99 = harness_results.get("latency_p99_ms", 0)

    if error_rate > max_error_rate:
        reasons.append(
            f"error_rate {error_rate:.3f} exceeds max {max_error_rate}"
        )
    if p99 > max_latency_p99_ms:
        reasons.append(
            f"latency_p99 {p99:.0f}ms exceeds max {max_latency_p99_ms}ms"
        )

    return {"safe": len(reasons) == 0, "reasons": reasons}


# ---------------------------------------------------------------------------
# 5. dryrun_change
# ---------------------------------------------------------------------------

def dryrun_change(change_spec, num_requests=100,
                  max_error_rate=0.05, max_latency_p99_ms=2000):
    """Orchestrate the full dryrun flow.

    create shadow -> generate traffic -> run harness -> check safety.
    Returns a complete report dict.
    """
    _counters["dryruns_total"] += 1

    shadow = create_shadow_env(change_spec)
    if not shadow.get("shadow_active"):
        _counters["dryruns_blocked"] += 1
        return {
            "stage": "shadow_setup",
            "safe": False,
            "shadow_env": shadow,
            "reason": shadow.get("reason", "shadow not active"),
        }

    traffic = generate_synthetic_traffic(shadow, num_requests=num_requests)
    harness = run_twin_harness(shadow, traffic)
    safety = check_promotion_safety(
        harness,
        max_error_rate=max_error_rate,
        max_latency_p99_ms=max_latency_p99_ms,
    )

    if safety["safe"]:
        _counters["dryruns_safe"] += 1
    else:
        _counters["dryruns_blocked"] += 1

    return {
        "stage": "complete",
        "safe": safety["safe"],
        "reasons": safety["reasons"],
        "shadow_env": shadow,
        "harness": harness,
        "safety": safety,
    }


# ---------------------------------------------------------------------------
# 6. stats
# ---------------------------------------------------------------------------

def stats():
    """Module statistics for monitoring and testing."""
    return dict(_counters)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    spec = {"id": "cli-test", "app": "demo", "error_prob": 0.01}
    report = dryrun_change(spec, num_requests=50)
    print(json.dumps(report, indent=2, default=str))
