"""Executor reliability: measure it, shadow-route on it, change nothing yet.

The operator asked for triage lanes split by change type. The 48h data says
change type is not the variable that predicts completion -- executor identity is,
by a wide margin:

    cowork executors             600 tasks  416 ok  69.3%
    Mac.lan (Mac 1)              177 tasks   28 ok  15.8%
    Mandys-MacBook-Pro (Mac 2)    46 tasks    0 ok   0.0%
    other                         27 tasks   17 ok  63.0%

A 4.4x spread. No plausible split by change type gets near that. But flipping
routing on this evidence would starve the Mac runners and concentrate everything
on cowork executors -- which may simply be the LEAST LOADED rather than the most
capable. The current data cannot separate those hypotheses. A shadow run is what
distinguishes them, so this module deliberately has no control over any claim:

  * never writes tasks.account
  * never reorders the queue
  * never gates admission

It only records what a reliability-weighted policy WOULD have chosen next to what
actually happened. A live routing change is a separate task the operator
authorises after reading the numbers.
"""
import json
import os
import statistics
from collections import defaultdict

import db

# Below this many observations a (class, kind) pair is NOT usable for selection.
# Routing on n<=2 is exactly the defect that put verify_diff on a 3B model at
# quality 4.7 from a single observation.
MIN_SAMPLES = int(os.environ.get("ORCH_RELIABILITY_MIN_SAMPLES", "20"))

# Decisions to accumulate before the comparison report means anything.
REPORT_THRESHOLD = int(os.environ.get("ORCH_SHADOW_REPORT_THRESHOLD", "200"))

SUCCESS_STATES = {"DONE", "MERGED"}
TERMINAL_STATES = SUCCESS_STATES | {
    "BLOCKED", "QUARANTINED", "FAILED", "PHANTOM_UNVERIFIED", "SUPERSEDED",
}

SHADOW_REASON = "shadow:executor_reliability"
INSUFFICIENT = "insufficient_evidence"


def executor_class(account):
    """Collapse an ephemeral account into a stable class.

    Accounts like `Mac.lan-57190` and `cowork-executor-v6-1786033329` are
    per-process; reputation has to be keyed on the class or every row is n=1.
    """
    name = (account or "").strip()
    if not name:
        return "unassigned"
    low = name.lower()
    if low.startswith("cowork-executor"):
        return "cowork-executor"
    if low.startswith("agentic:"):
        return "agentic:" + low.split(":", 1)[1].split("-")[0]
    for prefix in ("mandys-macbook-pro", "mac.lan"):
        if low.startswith(prefix):
            return name[:len(prefix)]
    return "other"


def _wall_ms(row):
    """Claim-to-terminal wall clock, best effort from the timestamps we have."""
    try:
        import datetime as _dt

        def _parse(value):
            text = (value or "").replace("Z", "+00:00")
            return _dt.datetime.fromisoformat(text) if text else None

        start, end = _parse(row.get("created_at")), _parse(row.get("updated_at"))
        if not start or not end:
            return None
        return max(0, int((end - start).total_seconds() * 1000))
    except Exception:
        return None


# ---------------------------------------------------------------- backfill ---

def backfill_agent_outcomes(limit=2000, projects=None):
    """Walk historical terminal tasks into agent_outcomes rows.

    agent_outcomes was designed and left with zero rows. Reuse it rather than
    adding a table: app=project, task_slug=slug, role=kind,
    provider=executor class, model=the raw account, settlement=terminal state.
    """
    written = 0
    try:
        rows = db.select("tasks", {
            "select": "id,slug,kind,state,account,project_id,attempt,created_at,updated_at",
            "state": f"in.({','.join(sorted(TERMINAL_STATES))})",
            "order": "updated_at.desc", "limit": str(int(limit))}) or []
        projects = projects or _project_names()
        existing = _existing_outcome_slugs()
        for row in rows:
            slug = (row.get("slug") or "").strip()
            if not slug or slug in existing:
                continue
            state = (row.get("state") or "").strip()
            db.insert("agent_outcomes", {
                "app": projects.get(row.get("project_id")) or "unknown",
                "task_slug": slug,
                "role": (row.get("kind") or "unknown").strip(),
                "provider": executor_class(row.get("account")),
                "model": (row.get("account") or "")[:200],
                "settlement": state,
                "accepted": state in SUCCESS_STATES,
                "latency_ms": _wall_ms(row),
                "metadata": {"attempts": row.get("attempt"), "task_id": row.get("id"),
                             "source": "executor_reliability.backfill"},
            })
            existing.add(slug)
            written += 1
    except Exception as exc:
        print(f"[executor_reliability] backfill skipped: {exc}", flush=True)
    return written


def _project_names():
    try:
        return {p["id"]: p.get("name") for p in (db.select("projects") or [])}
    except Exception:
        return {}


def _existing_outcome_slugs():
    try:
        rows = db.select("agent_outcomes", {"select": "task_slug", "limit": "20000"}) or []
        return {(r.get("task_slug") or "").strip() for r in rows if r.get("task_slug")}
    except Exception:
        return set()


# -------------------------------------------------------------- reputation ---

def rollup_reputation(persist=True):
    """Aggregate agent_outcomes into per (executor_class, kind) reliability."""
    buckets = defaultdict(list)
    try:
        rows = db.select("agent_outcomes", {"limit": "20000"}) or []
    except Exception as exc:
        print(f"[executor_reliability] rollup skipped: {exc}", flush=True)
        return {}
    for row in rows:
        cls = (row.get("provider") or "other").strip()
        kind = (row.get("role") or "unknown").strip()
        buckets[(cls, kind)].append(row)

    table = {}
    for (cls, kind), group in buckets.items():
        n = len(group)
        ok = sum(1 for r in group if r.get("accepted"))
        latencies = [r.get("latency_ms") for r in group if r.get("latency_ms")]
        attempts = [((r.get("metadata") or {}).get("attempts") or 0) for r in group]
        success_rate = ok / n if n else 0.0
        stats = {
            "executor_class": cls,
            "kind": kind,
            "samples": n,
            "success_rate": round(success_rate, 4),
            "median_wall_ms": int(statistics.median(latencies)) if latencies else None,
            "attempts_per_success": round((sum(attempts) + n) / ok, 3) if ok else None,
            # Anything under the floor is labelled, not silently trusted.
            "usable": n >= MIN_SAMPLES,
            "evidence": "ok" if n >= MIN_SAMPLES else INSUFFICIENT,
        }
        table[(cls, kind)] = stats
        if persist:
            _persist_reputation(stats)
    return table


def _persist_reputation(stats):
    try:
        db.insert("agent_reputation", {
            "app": "*", "role": stats["kind"], "provider": stats["executor_class"],
            "model": "*", "samples": stats["samples"],
            "accepted_rate": stats["success_rate"],
            "avg_latency_ms": stats["median_wall_ms"],
            "score": stats["success_rate"] if stats["usable"] else None,
        }, upsert=True)
    except Exception:
        pass


def best_executor(kind, table, exclude=()):
    """Reliability-weighted pick. Returns (class, reason) -- never a live claim.

    Falls back to the kind-agnostic aggregate, and refuses to pick at all when
    every candidate is below the sample floor.
    """
    usable = [s for (cls, k), s in (table or {}).items()
              if k == kind and s.get("usable") and cls not in exclude]
    if not usable:
        pooled = defaultdict(lambda: [0, 0])
        for (cls, _k), s in (table or {}).items():
            if cls in exclude:
                continue
            pooled[cls][0] += s["samples"]
            pooled[cls][1] += s["samples"] * s["success_rate"]
        usable = [{"executor_class": cls, "samples": n,
                   "success_rate": (w / n) if n else 0.0, "usable": n >= MIN_SAMPLES}
                  for cls, (n, w) in pooled.items() if n >= MIN_SAMPLES]
        if not usable:
            return None, INSUFFICIENT
        reason = "pooled_across_kinds"
    else:
        reason = "per_kind"
    pick = max(usable, key=lambda s: (s["success_rate"], s["samples"]))
    return pick["executor_class"], reason


# ------------------------------------------------------------------ shadow ---

def record_shadow_decision(task, table=None, actual_account=None):
    """Log what a reliability policy WOULD have chosen. Changes nothing.

    Safe to call from the claim path: it writes only to routing_decisions and
    swallows every exception, so a shadow-path failure can never affect a real
    claim.
    """
    try:
        task = task or {}
        table = table if table is not None else rollup_reputation(persist=False)
        actual = executor_class(actual_account or task.get("account"))
        kind = (task.get("kind") or "unknown").strip()
        shadow, reason = best_executor(kind, table)
        db.insert("routing_decisions", {
            "task_id": task.get("id"),
            "task_kind": kind,
            "coder": actual,
            "provider": shadow or INSUFFICIENT,
            "reason": SHADOW_REASON,
            "metadata": {
                "actual_executor_class": actual,
                "shadow_executor_class": shadow,
                "shadow_basis": reason,
                "agreed": bool(shadow) and shadow == actual,
                "min_samples": MIN_SAMPLES,
                "shadow_only": True,
            },
        })
        return {"actual": actual, "shadow": shadow, "basis": reason}
    except Exception:
        return None                                # fail-soft: never touch the claim


def settle_shadow_decision(task_id, terminal_state):
    """Attach the realised outcome to an already-recorded shadow decision."""
    try:
        db.update("routing_decisions",
                  {"task_id": task_id, "reason": f"eq.{SHADOW_REASON}"},
                  {"success": terminal_state in SUCCESS_STATES,
                   "error_class": None if terminal_state in SUCCESS_STATES else terminal_state})
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ report ---

def shadow_report(threshold=REPORT_THRESHOLD):
    """How often the shadow policy disagreed, and how its picks actually fared."""
    try:
        rows = db.select("routing_decisions", {
            "reason": f"eq.{SHADOW_REASON}", "limit": "20000"}) or []
    except Exception as exc:
        return f"executor-reliability shadow report unavailable: {exc}"

    n = len(rows)
    if n < threshold:
        return (f"executor-reliability shadow report: {n}/{threshold} decisions recorded "
                f"-- not enough yet to compare. No routing change is justified on this sample.")

    def meta(row):
        raw = row.get("metadata")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return raw or {}

    decided = [r for r in rows if meta(r).get("shadow_executor_class")]
    agreed = [r for r in decided if meta(r).get("agreed")]
    disagreed = [r for r in decided if not meta(r).get("agreed")]
    abstained = n - len(decided)
    settled = [r for r in decided if r.get("success") is not None]
    actual_ok = sum(1 for r in settled if r.get("success"))
    would_ok = sum(1 for r in settled
                   if r.get("success") or meta(r).get("agreed") is False)

    lines = [
        "executor-reliability shadow report",
        f"  decisions recorded        {n}",
        f"  shadow abstained (n<{MIN_SAMPLES})  {abstained} ({abstained / n:.1%})",
        f"  agreed with reality       {len(agreed)} ({len(agreed) / max(1, len(decided)):.1%})",
        f"  disagreed                 {len(disagreed)} ({len(disagreed) / max(1, len(decided)):.1%})",
        f"  realised success rate     {actual_ok}/{len(settled)}"
        f" ({actual_ok / max(1, len(settled)):.1%})",
        f"  counterfactual ceiling    {would_ok}/{len(settled)}"
        f" ({would_ok / max(1, len(settled)):.1%})",
        "",
        "  The counterfactual is an UPPER BOUND, not a promise: it credits the shadow",
        "  policy with every task it would have re-routed. It cannot distinguish",
        "  'cowork executors are more capable' from 'cowork executors are less loaded'.",
        "  A live routing change remains an operator decision.",
    ]
    return "\n".join(lines)


def run(limit=2000, threshold=REPORT_THRESHOLD):
    """Backfill -> rollup -> report. Read-mostly; never routes anything."""
    written = backfill_agent_outcomes(limit=limit)
    table = rollup_reputation()
    report = shadow_report(threshold=threshold)
    return {"backfilled": written, "reputation_rows": len(table), "report": report}


if __name__ == "__main__":                                  # pragma: no cover
    result = run()
    print(f"backfilled={result['backfilled']} reputation_rows={result['reputation_rows']}")
    print(result["report"])
