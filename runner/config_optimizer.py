#!/usr/bin/env python3
"""
config_optimizer.py — Historical config analysis for fleet_control.py.

Analyzes past fleet_config changes and their correlation with task throughput,
merge success rates, and cost metrics. Recommends config adjustments based on
observed patterns rather than blind knob-turning.

Owner module: fleet_control.py
Slice-2 of: improve-centralized-configuration-management-wit
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _safe_import(mod):
    try:
        return __import__(mod)
    except Exception:
        return None

db = _safe_import("db")

# How far back to look for config change impact (hours)
LOOKBACK_HOURS = int(os.environ.get("ORCH_CONFIG_LOOKBACK_HOURS", "24"))
# Minimum throughput improvement to recommend a config change
MIN_THROUGHPUT_GAIN = float(os.environ.get("ORCH_CONFIG_MIN_GAIN", "0.10"))


def _throughput_around(timestamp_iso, window_hours=2):
    """Get task throughput (DONE count) in a window around a timestamp.

    Returns (before_count, after_count) for the window before and after the change.
    """
    if not db:
        return 0, 0
    try:
        before_start = (datetime.datetime.fromisoformat(timestamp_iso)
                        - datetime.timedelta(hours=window_hours)).isoformat()
        after_end = (datetime.datetime.fromisoformat(timestamp_iso)
                     + datetime.timedelta(hours=window_hours)).isoformat()

        # COUNT class, both sides. These feed a before/after throughput comparison, and
        # len() of a 1,000-row page silently clamps BOTH sides to 1,000 — which makes a
        # busy window look identical to a busier one and reports "no change" from a
        # genuine improvement.
        before = db.count("tasks", {
            "state": "eq.DONE",
            "updated_at": f"gte.{before_start}",
            "and": f"(updated_at.lt.{timestamp_iso})",
        })
        after = db.count("tasks", {
            "state": "eq.DONE",
            "updated_at": f"gte.{timestamp_iso}",
            "and": f"(updated_at.lt.{after_end})",
        })
        return before, after
    except Exception:
        return 0, 0


def analyze_config_history():
    """Analyze fleet_config changes and their impact on throughput.

    Returns list of dicts: [{key, old_value, new_value, impact, recommendation}]
    """
    if not db:
        return []
    try:
        cutoff = (datetime.datetime.utcnow()
                  - datetime.timedelta(hours=LOOKBACK_HOURS)).isoformat()
        # Look for config audit trail if available
        changes = db.select("fleet_config_audit", {
            "select": "*",
            "created_at": f"gte.{cutoff}",
            "order": "created_at.desc",
            "limit": "50"
        }) or []
    except Exception:
        changes = []

    results = []
    for ch in changes:
        key = ch.get("key", "")
        ts = ch.get("created_at", "")
        if not ts:
            continue
        before, after = _throughput_around(ts)
        if before == 0:
            impact = "unknown"
            recommendation = "insufficient_data"
        elif after >= before * (1 + MIN_THROUGHPUT_GAIN):
            impact = "positive"
            recommendation = "keep"
        elif after <= before * (1 - MIN_THROUGHPUT_GAIN):
            impact = "negative"
            recommendation = "revert"
        else:
            impact = "neutral"
            recommendation = "keep"

        results.append({
            "key": key,
            "old_value": ch.get("old_value"),
            "new_value": ch.get("new_value"),
            "before_throughput": before,
            "after_throughput": after,
            "impact": impact,
            "recommendation": recommendation,
        })
    return results


def suggest_config_changes():
    """Based on current fleet state, suggest config knob changes.

    Looks at queue pressure and recent merge rates to suggest adjustments
    to MAX_PARALLEL, MERGE_TRAIN_*_BATCH, etc.
    """
    if not db:
        return []
    suggestions = []
    try:
        # COUNT class: server-side exact count, never len() of a page.
        # Until 2026-08-06 this was `len(select(..., limit="1000"))`, so queue_depth was
        # structurally incapable of exceeding 1,000. At the 1,407 measured that day the
        # autoscaler believed the queue was 1,000 deep; at 10,000 it would still have
        # believed 1,000. Every parallelism decision below reads this number.
        queue_depth = db.count("tasks", {"state": "eq.QUEUED"})

        current_parallel = int(os.environ.get("MAX_PARALLEL_CEILING", "4"))

        # If queue is deep and throughput is healthy, suggest increasing parallelism
        if queue_depth > 50 and current_parallel < 8:
            suggestions.append({
                "key": "MAX_PARALLEL_CEILING",
                "current": current_parallel,
                "suggested": min(current_parallel + 2, 8),
                "reason": f"Queue depth={queue_depth}, consider increasing parallelism",
            })
        elif queue_depth < 5 and current_parallel > 2:
            suggestions.append({
                "key": "MAX_PARALLEL_CEILING",
                "current": current_parallel,
                "suggested": max(current_parallel - 1, 2),
                "reason": f"Queue depth={queue_depth}, can reduce parallelism to save cost",
            })
    except Exception:
        pass
    return suggestions


def query_history(records, start=None, end=None, config_key=None):
    """Historical config records filtered by date range and config key.

    `analyze_config_history()` answers "did this one change help?" one row at a
    time. Answering "which knob actually tracks queue depth?" needs the SERIES,
    so this is the read side: an inclusive [start, end] window over
    `created_at`, optionally narrowed to a single config key.

    Records are passed in rather than fetched so the caller owns the source —
    the live audit trail, or a synthetic set under test. Fail-soft: an
    unparseable timestamp drops that record instead of raising.
    """
    out = []
    for row in records or []:
        if config_key is not None and row.get("key") != config_key:
            continue
        ts = _parse_ts(row.get("created_at"))
        if ts is None:
            continue
        if start is not None and ts < _parse_ts(start):
            continue
        if end is not None and ts > _parse_ts(end):
            continue
        out.append(row)
    out.sort(key=lambda r: _parse_ts(r.get("created_at")))
    return out


def _parse_ts(value):
    """ISO-8601 to datetime, tolerating a trailing Z and a missing time part."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def correlate(records, param, metric="queue_depth"):
    """Pearson r between a config parameter and an observed metric.

    Returns {'r', 'n', 'param', 'metric'} with r=None when it is undefined —
    fewer than two usable pairs, or one side constant (zero variance), where a
    coefficient would be a divide-by-zero rather than "no relationship". Callers
    gate on a threshold, so a fabricated 0.0 there would read as a real finding.

    Deliberately dependency-free: numpy/scipy are not runner dependencies and
    one correlation does not justify adding them.
    """
    xs, ys = [], []
    for row in records or []:
        x, y = row.get(param), row.get(metric)
        if x is None or y is None:
            continue
        try:
            xs.append(float(x))
            ys.append(float(y))
        except (TypeError, ValueError):
            continue
    n = len(xs)
    if n < 2:
        return {"r": None, "n": n, "param": param, "metric": metric}
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0 or syy <= 0:
        return {"r": None, "n": n, "param": param, "metric": metric}
    return {"r": sxy / ((sxx ** 0.5) * (syy ** 0.5)), "n": n,
            "param": param, "metric": metric}


def stats():
    """Return optimizer summary."""
    return {
        "lookback_hours": LOOKBACK_HOURS,
        "min_throughput_gain": MIN_THROUGHPUT_GAIN,
    }
