#!/usr/bin/env python3
"""bottleneck_detector.py — REQUIREMENT A: proposals may only originate from a MEASURED bottleneck.

The old miner asked a model "how would you make this 20-500x better?" and stored whatever
came back. 934 proposals later, 76% shared three self-reported score values and not one
carried a number that could be checked.

This module replaces the template with measurement. Each COLLECTOR is a named metric with:
  * an executable SQL body (run read-only through the orch_metric_scalar RPC),
  * a direction (`lt` = lower is better),
  * an `ideal` value that the metric would take if this bottleneck did not exist.

HEADROOM (the honest form of "100x"):
    headroom = current / ideal            for 'lt' metrics (e.g. 96.4% bad / 5% floor = 19x)
    headroom = ideal / current            for 'gt' metrics (e.g. 100% target / 11.4% now = 8.8x)

Headroom is derived from the measurement, not asserted by a model. A stage burning 90% of
wall-clock has 10x of headroom and no more; claiming 100x for it is arithmetically false and
this module will not emit it. Candidates are RANKED BY HEADROOM, so the loop naturally aims
at order-of-magnitude targets — but only where the data says the order of magnitude is there.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import gate_liveness

WINDOW_DAYS = int(os.environ.get("ORCH_BOTTLENECK_WINDOW_DAYS", "14"))
MIN_HEADROOM = float(os.environ.get("ORCH_MIN_HEADROOM", "2.0"))
MIN_SAMPLE = int(os.environ.get("ORCH_BOTTLENECK_MIN_SAMPLE", "20"))

_W = f"now() - interval '{WINDOW_DAYS} days'"

# key -> (surface, metric_name, comparator, ideal, sql, sample_sql, human)
COLLECTORS = {
    "shipped_without_commit_pct": (
        "reliability", "pct_shipped_tasks_with_no_artifact_commit", "lt", 5.0,
        f"select round(100.0*count(*) filter (where artifact_commit is null)"
        f"/greatest(count(*),1),2) from tasks where created_at > {_W} "
        f"and state in ('MERGED','DEPLOYED_AND_VERIFIED','DONE')",
        f"select count(*) from tasks where created_at > {_W} "
        f"and state in ('MERGED','DEPLOYED_AND_VERIFIED','DONE')",
        "tasks declared shipped that carry no commit evidence"),
    "merge_to_deploy_pct": (
        "orchestration-layer", "pct_merged_tasks_reaching_verified_deploy", "gt", 90.0,
        f"select round(100.0*count(*) filter (where state='DEPLOYED_AND_VERIFIED')"
        f"/greatest(count(*) filter (where state in ('MERGED','DEPLOYED_AND_VERIFIED')),1),2) "
        f"from tasks where created_at > {_W}",
        f"select count(*) from tasks where created_at > {_W} "
        f"and state in ('MERGED','DEPLOYED_AND_VERIFIED')",
        "merged work that actually reaches a verified deploy"),
    "terminal_yield_pct": (
        "orchestration-layer", "pct_created_tasks_reaching_verified_deploy", "gt", 50.0,
        f"select round(100.0*count(*) filter (where state='DEPLOYED_AND_VERIFIED')"
        f"/greatest(count(*),1),3) from tasks where created_at > {_W}",
        f"select count(*) from tasks where created_at > {_W}",
        "created tasks that end in verified production"),
    "phantom_rate_pct": (
        "reliability", "pct_tasks_phantom_unverified", "lt", 1.0,
        f"select round(100.0*count(*) filter (where state='PHANTOM_UNVERIFIED')"
        f"/greatest(count(*),1),2) from tasks where created_at > {_W}",
        f"select count(*) from tasks where created_at > {_W}",
        "tasks that closed with unverifiable output"),
    "quarantine_rate_pct": (
        "reliability", "pct_tasks_quarantined", "lt", 2.0,
        f"select round(100.0*count(*) filter (where state='QUARANTINED')"
        f"/greatest(count(*),1),2) from tasks where created_at > {_W}",
        f"select count(*) from tasks where created_at > {_W}",
        "tasks quarantined out of the pipeline"),
    "first_try_yield_pct": (
        "developer-experience", "pct_merged_tasks_with_zero_remediation", "gt", 90.0,
        f"select round(100.0*count(*) filter (where coalesce(remediation_count,0)=0)"
        f"/greatest(count(*),1),2) from tasks where created_at > {_W} "
        f"and state in ('MERGED','DEPLOYED_AND_VERIFIED')",
        f"select count(*) from tasks where created_at > {_W} "
        f"and state in ('MERGED','DEPLOYED_AND_VERIFIED')",
        "merges achieved without a remediation cycle"),
    "cycle_time_hours": (
        "performance", "median_hours_task_created_to_merged", "lt", 1.0,
        f"select round((percentile_cont(0.5) within group "
        f"(order by extract(epoch from (updated_at-created_at))/3600.0))::numeric,2) "
        f"from tasks where created_at > {_W} and state in ('MERGED','DEPLOYED_AND_VERIFIED')",
        f"select count(*) from tasks where created_at > {_W} "
        f"and state in ('MERGED','DEPLOYED_AND_VERIFIED')",
        "median wall-clock from task creation to merge"),
    "release_failure_pct": (
        "reliability", "pct_releases_not_succeeding", "lt", 5.0,
        f"select round(100.0*count(*) filter (where coalesce(deploy_status,'')<>'success')"
        f"/greatest(count(*),1),2) from releases where created_at > {_W}",
        f"select count(*) from releases where created_at > {_W}",
        "release attempts that do not reach success"),
    "queue_backlog_ratio": (
        "cost-efficiency", "queued_tasks_per_verified_deploy", "lt", 5.0,
        f"select round(count(*) filter (where state='QUEUED')::numeric"
        f"/greatest(count(*) filter (where state='DEPLOYED_AND_VERIFIED'),1),2) "
        f"from tasks where created_at > {_W}",
        f"select count(*) from tasks where created_at > {_W}",
        "queued work carried per unit of delivered work"),
}


def scalar(sql):
    """Run a read-only scalar metric query. Returns float or None."""
    try:
        v = db.rpc("orch_metric_scalar", {"q": sql})
    except Exception as exc:
        print(f"[bottleneck_detector] metric query failed: {exc}", flush=True)
        return None
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = next(iter(v.values()), None)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def headroom(value, ideal, comparator):
    """Achievable multiple implied by the measurement. Never fabricated."""
    if value is None or ideal is None:
        return None
    if comparator == "lt":
        if value <= ideal or ideal <= 0:
            return 1.0
        return round(value / ideal, 2)
    if value <= 0:
        return None                       # 0% conversion -> unbounded; refuse to invent a number
    if value >= ideal:
        return 1.0
    return round(ideal / value, 2)


def measure(key):
    """Measure one collector. Returns a bottleneck dict or None when not measurable."""
    surface, metric, comparator, ideal, sql, sample_sql, human = COLLECTORS[key]
    value = scalar(sql)
    if value is None:
        gate_liveness.record("bottleneck_detector", "unmeasurable", key)
        return None
    n = scalar(sample_sql)
    n = int(n) if n is not None else 0
    if n < MIN_SAMPLE:
        gate_liveness.record("bottleneck_detector", "insufficient_sample", key, f"n={n}")
        return None
    h = headroom(value, ideal, comparator)
    if h is None:
        gate_liveness.record("bottleneck_detector", "unbounded", key, f"value={value}")
        return None
    bad = h >= MIN_HEADROOM
    gate_liveness.record("bottleneck_detector", "bottleneck" if bad else "healthy",
                         key, f"value={value} headroom={h}x n={n}")
    if not bad:
        return None
    return {"bottleneck_key": key, "surface": surface, "metric_name": metric,
            "metric_collector": key, "metric_query": sql, "value": value,
            "ideal_value": ideal, "comparator": comparator, "headroom_multiplier": h,
            "sample_n": n, "detail": f"{human}: {value} (ideal {ideal}, n={n})"}


def detect(persist=True):
    """Measure every collector; return only measurably-bad ones, ranked by headroom desc."""
    found = []
    for key in COLLECTORS:
        b = measure(key)
        if b:
            found.append(b)
    found.sort(key=lambda b: b["headroom_multiplier"], reverse=True)
    if persist:
        for b in found:
            try:
                db.insert("orch_bottlenecks", dict(b, app=None))
            except Exception as exc:
                print(f"[bottleneck_detector] persist failed for {b['bottleneck_key']}: {exc}")
    return found


def latest(key):
    """Most recent recorded measurement for a bottleneck key (used as a fallback baseline)."""
    rows = db.select("orch_bottlenecks", {
        "select": "*", "bottleneck_key": f"eq.{key}",
        "order": "detected_at.desc", "limit": "1"}) or []
    return rows[0] if rows else None


def run():
    found = detect()
    print(f"bottleneck_detector: {len(found)} measured bottleneck(s) "
          f"of {len(COLLECTORS)} collectors, window={WINDOW_DAYS}d")
    for b in found:
        print(f"  {b['headroom_multiplier']:>8.2f}x  {b['bottleneck_key']:<28} "
              f"{b['metric_name']} = {b['value']} (ideal {b['ideal_value']}, n={b['sample_n']})")
    return found


if __name__ == "__main__":
    run()
