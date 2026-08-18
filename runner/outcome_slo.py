"""
outcome_slo.py — Outcome SLOs extension, slice 1: build outcome QUALITY and LATENCY.

The existing `slo_controller` measures whether the fleet is MOVING (merge rate,
missing branches, backlog, fix age, utilisation). It does not measure whether
what it produces is GOOD, or how long it takes to produce it. This module adds
those two, as the first independently mergeable slice.

WHY THIS IS A SEPARATE MODULE, AND PURE
---------------------------------------
Every existing check in `slo_controller` fetches from the DB inside the check
function, so none of them can be exercised under a simulated load — which is
precisely what this task asks for ("verify SLO calculation accuracy under
different simulated load conditions"). The computation here is therefore PURE:
it takes a list of outcome rows and returns verdicts. `slo_controller` does the
fetching. That split is what makes the accuracy testable at all, and it is the
pattern the remaining SLO work should follow.

CONVENTIONS (repo CLAUDE.md)
----------------------------
- Fail-soft: nothing here raises on bad input. A malformed row is skipped, not
  fatal; a missing field is UNKNOWN, never silently 0.
- UNKNOWN is `ok: None`, matching the existing checks — `slo_controller.run()`
  already skips remediation for `ok is None`, so a thin or unreadable sample can
  never trigger an action. Reporting a green SLO from two data points would be
  worse than reporting nothing.
- All thresholds are `SLO_`-prefixed env vars with defaults, so they are
  fleet-pushable via `fleet_control.py`.
"""
import os
import logging

logger = logging.getLogger(__name__)

# ─── Thresholds (env-configurable, fleet-pushable) ───────────────────────────

#: Fraction of completed builds that must be "clean" (see `_is_clean`).
SLO_OUTCOME_QUALITY = float(os.environ.get("SLO_OUTCOME_QUALITY", "0.75"))
#: p95 wall-clock seconds for a completed build.
SLO_BUILD_LATENCY_P95_S = float(os.environ.get("SLO_BUILD_LATENCY_P95_S", "900"))
#: Minimum completed builds before either SLO reports anything but UNKNOWN.
SLO_OUTCOME_MIN_SAMPLES = int(os.environ.get("SLO_OUTCOME_MIN_SAMPLES", "5"))
#: Attempts at or above which an outcome is no longer "clean", however it ended.
SLO_MAX_CLEAN_ATTEMPTS = int(os.environ.get("SLO_MAX_CLEAN_ATTEMPTS", "1"))


def _num(value, default=None):
    """Coerce to float, or return `default`. Never raises."""
    if isinstance(value, bool):  # bool is an int subclass; never a measurement
        return default
    try:
        if value is None:
            return default
        n = float(value)
        return n if n == n and n not in (float("inf"), float("-inf")) else default
    except (TypeError, ValueError):
        return default


def _completed(row):
    """A build counts toward the SLOs once it reached a terminal verdict."""
    return bool(row.get("tests_passed")) or bool(row.get("integrated"))


def _is_clean(row):
    """
    A CLEAN outcome: integrated, tests green, first attempt, no review failures,
    not rate-limited.

    Deliberately stricter than "integrated". Merge rate already measures whether
    something landed; quality measures whether it landed WELL. A change that
    merged on its fourth attempt after two review failures is a cost the merge
    rate hides, and hiding it is how a fleet convinces itself it is healthy
    while burning retries.
    """
    if not row.get("integrated") or not row.get("tests_passed"):
        return False
    if row.get("rate_limited"):
        return False
    attempts = _num(row.get("attempts"), 1)
    if attempts is not None and attempts > SLO_MAX_CLEAN_ATTEMPTS:
        return False
    review_failures = _num(row.get("review_failures"), 0)
    if review_failures is not None and review_failures > 0:
        return False
    return True


def percentile(values, pct):
    """
    Nearest-rank percentile over a list of numbers. Returns None for an empty
    list. Nearest-rank (not interpolated) because a p95 latency must be a
    latency that actually happened — an interpolated value is a number no build
    ever took, which is a poor thing to page someone about.
    """
    nums = sorted(v for v in (_num(v) for v in (values or [])) if v is not None)
    if not nums:
        return None
    p = min(100.0, max(0.0, _num(pct, 0) or 0))
    rank = max(1, int(-(-len(nums) * p // 100)))  # ceil without float error
    return nums[min(rank, len(nums)) - 1]


# ─── The two SLOs ────────────────────────────────────────────────────────────

def compute_outcome_quality(outcomes, threshold=None, min_samples=None):
    """
    Fraction of completed builds that were CLEAN.

    Returns a check dict in the same shape the existing `slo_controller` checks
    use: `{ok, value, threshold, ...}` with `ok: None` for UNKNOWN.
    """
    thr = _num(threshold, SLO_OUTCOME_QUALITY)
    floor = int(min_samples if min_samples is not None else SLO_OUTCOME_MIN_SAMPLES)
    rows = [r for r in (outcomes or []) if isinstance(r, dict)]

    completed = [r for r in rows if _completed(r)]
    clean = [r for r in completed if _is_clean(r)]

    if len(completed) < floor:
        return {
            "ok": None, "state": "UNKNOWN", "value": None, "threshold": thr,
            "completed": len(completed), "clean": len(clean), "samples": len(rows),
            "reason": f"only {len(completed)} completed build(s); need {floor}",
        }

    rate = len(clean) / len(completed)
    return {
        "ok": rate >= thr,
        "value": round(rate, 4),
        "threshold": thr,
        "completed": len(completed),
        "clean": len(clean),
        "samples": len(rows),
        "retried": sum(1 for r in completed if (_num(r.get("attempts"), 1) or 1) > SLO_MAX_CLEAN_ATTEMPTS),
        "review_failed": sum(1 for r in completed if (_num(r.get("review_failures"), 0) or 0) > 0),
        "rate_limited": sum(1 for r in completed if r.get("rate_limited")),
    }


def compute_build_latency(outcomes, threshold_s=None, min_samples=None):
    """
    p95 wall-clock seconds for completed builds (p50 reported alongside).

    Only rows with a usable `wall_ms` are measured. Rows missing it are counted
    in `unmeasured` rather than being treated as fast — an unmeasured build is
    not a quick one.
    """
    thr = _num(threshold_s, SLO_BUILD_LATENCY_P95_S)
    floor = int(min_samples if min_samples is not None else SLO_OUTCOME_MIN_SAMPLES)
    rows = [r for r in (outcomes or []) if isinstance(r, dict)]
    completed = [r for r in rows if _completed(r)]

    seconds, unmeasured = [], 0
    for r in completed:
        ms = _num(r.get("wall_ms"))
        if ms is None or ms < 0:
            unmeasured += 1
            continue
        seconds.append(ms / 1000.0)

    if len(seconds) < floor:
        return {
            "ok": None, "state": "UNKNOWN", "value": None, "threshold": thr,
            "measured": len(seconds), "unmeasured": unmeasured, "completed": len(completed),
            "reason": f"only {len(seconds)} measured build(s); need {floor}",
        }

    p95 = percentile(seconds, 95)
    return {
        "ok": p95 <= thr,
        "value": round(p95, 2),
        "threshold": thr,
        "p50_s": round(percentile(seconds, 50), 2),
        "p95_s": round(p95, 2),
        "max_s": round(max(seconds), 2),
        "measured": len(seconds),
        "unmeasured": unmeasured,
        "completed": len(completed),
    }


def evaluate_outcome_slos(outcomes):
    """Both new SLOs, keyed as `slo_controller` keys its checks."""
    return {
        "outcome_quality": compute_outcome_quality(outcomes),
        "build_latency": compute_build_latency(outcomes),
    }


# ─── Operator report ─────────────────────────────────────────────────────────

def _verdict(check):
    if check.get("ok") is None:
        return "UNKNOWN"
    return "PASS" if check.get("ok") else "FAIL"


def render_report(checks, title="Outcome SLOs"):
    """
    Plain-text operator report. Deterministic and dependency-free so it can be
    written to a control row, printed by the periodic runner, or diffed.
    """
    checks = checks or {}
    lines = [f"=== {title} ==="]

    q = checks.get("outcome_quality") or {}
    lines.append(f"[{_verdict(q)}] outcome_quality: "
                 + (f"{q.get('value')} (threshold >= {q.get('threshold')})"
                    if q.get("value") is not None else f"UNKNOWN — {q.get('reason', 'no data')}"))
    if q.get("completed"):
        lines.append(f"        {q.get('clean', 0)}/{q.get('completed')} clean; "
                     f"retried={q.get('retried', 0)} review_failed={q.get('review_failed', 0)} "
                     f"rate_limited={q.get('rate_limited', 0)}")

    l = checks.get("build_latency") or {}
    lines.append(f"[{_verdict(l)}] build_latency_p95_s: "
                 + (f"{l.get('value')} (threshold <= {l.get('threshold')})"
                    if l.get("value") is not None else f"UNKNOWN — {l.get('reason', 'no data')}"))
    if l.get("measured"):
        lines.append(f"        p50={l.get('p50_s')}s p95={l.get('p95_s')}s max={l.get('max_s')}s "
                     f"measured={l.get('measured')} unmeasured={l.get('unmeasured', 0)}")

    failing = [k for k, c in checks.items() if c.get("ok") is False]
    unknown = [k for k, c in checks.items() if c.get("ok") is None]
    lines.append(f"-- {len(checks) - len(failing) - len(unknown)}/{len(checks)} passing"
                 + (f"; FAILING: {', '.join(sorted(failing))}" if failing else "")
                 + (f"; UNKNOWN: {', '.join(sorted(unknown))}" if unknown else ""))
    return "\n".join(lines)
