#!/usr/bin/env python3
"""
ev_scheduler.py - EV-per-token task ordering. Scores every QUEUED task by expected value
per token spent, so the swarm burns budget on work that plausibly moves revenue first.

score(task, ctx) heuristic (deterministic, unit-testable):
    base   = log10(1 + MRR of the task's project)           # revenue-weighted
    s      = base * success_rate / (avg_usd + 0.5)          # discount by cost + failure odds
    s     *= (1 + min(kind_delta, 100)/100) if that task KIND has shown positive
             revenue-per-merge in ctx["surface_returns"] (from revenue_attribution.kind_roi)
    s     *= 1.5  if kind == 'build' and prompt mentions revenue/pricing/growth/conversion
    s     *= 2.0  if slug is an APPROVED business-model check (ctx["approved_slugs"])
    s     *= 0.3  if transient_retries >= 2                  # flaky work is discounted

ctx = {"revenue_by_project": {name: mrr}, "surface_returns": {kind: avg_delta},
       "outcome_stats": {project: {"success_rate", "avg_usd"}}, "approved_slugs": set()}

PRIORITY STORAGE CHOICE (apply_ranking):
    1. If tasks has a real 'priority' column (probed via select=priority&limit=1 in
       try/except — PostgREST 400s on unknown columns), write rank 1..50 there (lower
       = claimed first, matching claim_task's ascending priority sort).
    2. Otherwise write ONE 'controls' row: insert({"key":"ev_ranking","value":<json of
       top-100 ids>}, upsert=True) — a single advisory row the claim loop can consult,
       zero schema risk to tasks.
    3. If controls rejects key/value too (the live controls table is scope/paused-shaped,
       see kill_switch.py), last-resort: write a 0..1 rank score into tasks.confidence
       for the top 50 (higher = better). Chosen because 'confidence' already exists and
       is numeric; the cascade guarantees SOME storage works without schema changes.

park_zero_ev(): legacy name. It no longer blocks work; tasks scoring < 0.01 are annotated
and deprioritized, but remain QUEUED so the implementation pipeline continues.
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import thermal_map

TOP_N = 50                 # tasks that receive an explicit priority write
CONTROLS_TOP = 100         # ids stored in the controls ev_ranking row
PARK_CAP = 20              # max tasks parked per run
ZERO_EV = 0.01             # scores below this are "near-zero"
PARK_NOTE = "[ev-low-priority: near-zero expected value — keep queued, run when capacity allows]"
BOOST_KINDS = ("build",)
REVENUE_WORDS = ("revenue", "pricing", "growth", "conversion")

# Outcome weighting: when ORCH_EV_OUTCOME_WEIGHTING=true, task-family priority is
# weighted by REALIZED outcomes (merged-and-stayed-green rate, retries, human-reject
# rate) rather than flat cost only. Default OFF so current scheduling is byte-identical.
OUTCOME_WEIGHTING_ENABLED = os.environ.get("ORCH_EV_OUTCOME_WEIGHTING", "false").lower() in ("true", "1", "yes")

# LOW-EV EARLY EXIT — refuse at the door instead of shelving later (2026-08-06).
#
# Low-value work is currently removed AFTER it is queued, by the queue-velocity PID
# shelving "lowest-EV work" once its integral crosses a threshold
# (queue_velocity.py:189). That ordering has a cost: a task with no business being queued
# still lands in the queue, still counts toward the depth the PID integrates, and so helps
# push the integral over the line that shelves OTHER tasks. Integral windup driven by work
# nobody wanted queued in the first place.
#
# A task refused BEFORE enqueue is never in the depth, so it can never contribute to the
# integral. That is the property the sibling fix-pid-integral-windup slice needs, and it is
# established here at the source rather than compensated for downstream.
#
# Two safety properties, both deliberate and both tested:
#   * LOW_EV_THRESHOLD defaults to 0.0 with a strict `<` comparison, so out of the box only
#     NEGATIVE-EV tasks are refused and current scheduling is unchanged. Note this is a
#     LOWER bar than the pre-existing ZERO_EV=0.01 parking threshold — refusing is
#     stronger than parking, so it must be harder to trigger, not easier.
#   * a task whose EV cannot be determined is NEVER refused. You do not discard work you
#     could not measure; that would silently drop every task from a producer which has not
#     adopted the EV field.
# Escalated/pinned work bypasses the check entirely: recovery and breach-remediation exist
# precisely for tasks whose value is not expressible as EV.
LOW_EV_THRESHOLD = float(os.environ.get("ORCH_LOW_EV_THRESHOLD", "0"))
LOW_EV_EARLY_EXIT = os.environ.get("ORCH_LOW_EV_EARLY_EXIT", "true").lower() in ("true", "1", "yes", "on")
LOW_EV_SKIP_NOTE = "[ev-early-exit: expected value below LOW_EV_THRESHOLD — not enqueued]"
# Slug prefixes whose value is not expressible as EV. Never early-exited.
LOW_EV_EXEMPT_PREFIXES = ("recovery", "recover-missing-branch-", "breach-remediation",
                          "canary-", "qafix-", "relfix-", "buildfix-", "deployfix-",
                          "toolchain-repair", "rework-")

_EV_FIELDS = ("ev", "expected_value", "score", "value")


def task_ev(task):
    """The task's expected value as a float, or None when it cannot be determined.

    None is meaningfully different from 0.0: 0.0 is a measured verdict, None means no
    producer ever supplied one. Only the former is eligible for refusal.
    """
    if not isinstance(task, dict):
        return None
    for field in _EV_FIELDS:
        if field not in task:
            continue
        raw = task.get(field)
        if raw is None or isinstance(raw, bool):
            continue                       # bools are not EVs; True would read as 1.0
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value != value or value in (float("inf"), float("-inf")):
            continue                       # NaN / inf are not measurements
        return value
    return None


def _low_ev_exempt(task):
    slug = str((task or {}).get("slug") or "").lower()
    kind = str((task or {}).get("kind") or "").lower()
    if kind in ("recovery", "canary", "toolchain-repair"):
        return True
    return slug.startswith(LOW_EV_EXEMPT_PREFIXES)


def should_enqueue(task, ev=None, threshold=None):
    """Pre-queue gate. Returns a verdict dict; never raises.

    {"enqueue": bool, "reason": str, "ev": float|None, "threshold": float,
     "counts_toward_pid": bool}

    `counts_toward_pid` is False exactly when the task is refused: a task that never
    enters the queue must never be integrated by the queue-velocity PID. Callers that
    keep their own PID accounting should honour it; callers that derive depth from the
    queue itself get the property for free, because the task simply is not there.
    """
    limit = LOW_EV_THRESHOLD if threshold is None else float(threshold)
    verdict = {"enqueue": True, "ev": None, "threshold": limit, "counts_toward_pid": True}
    try:
        if not LOW_EV_EARLY_EXIT:
            verdict["reason"] = "early exit disabled (ORCH_LOW_EV_EARLY_EXIT)"
            return verdict
        if _low_ev_exempt(task):
            verdict["reason"] = "exempt: value not expressible as EV"
            return verdict
        value = task_ev(task) if ev is None else ev
        try:
            value = None if value is None else float(value)
        except (TypeError, ValueError):
            value = None
        verdict["ev"] = value
        if value is None:
            verdict["reason"] = "EV unknown — never refuse unmeasured work"
            return verdict
        if value < limit:
            verdict.update(enqueue=False, counts_toward_pid=False,
                           reason=f"EV {value:.4f} below threshold {limit:.4f}")
            print(f"[ev-scheduler] early exit: not enqueuing "
                  f"{task.get('slug') or task.get('id') or '<unknown>'} — "
                  f"{verdict['reason']}; treated as shelved "
                  f"(excluded from queue-velocity PID)", flush=True)
            return verdict
        verdict["reason"] = f"EV {value:.4f} at or above threshold {limit:.4f}"
        return verdict
    except Exception as e:                 # fail-open: a broken gate must not drop work
        verdict["reason"] = f"gate error, enqueuing anyway ({e})"
        return verdict


def filter_enqueueable(tasks, threshold=None):
    """Split an iterable of tasks into (enqueue, skipped_verdicts).

    Skipped entries are (task, verdict) pairs so a caller can annotate them as shelved
    without re-deriving why.
    """
    keep, skipped = [], []
    for task in (tasks or []):
        verdict = should_enqueue(task, threshold=threshold)
        if verdict["enqueue"]:
            keep.append(task)
        else:
            skipped.append((task, verdict))
    return keep, skipped


def outcome_weight(task, ctx):
    """Compute an outcome-based weight multiplier for a task's kind family.

    Uses learn_from_merges signals via ctx["family_outcomes"]:
      {kind: {"merged_green": int, "total": int, "retries": int, "rejected": int}}

    Returns a multiplier >= 0.1. Higher realized success => higher multiplier.
    Only active when ORCH_EV_OUTCOME_WEIGHTING is true; otherwise returns 1.0.
    """
    if not OUTCOME_WEIGHTING_ENABLED:
        return 1.0
    family = (ctx.get("family_outcomes") or {})
    kind = (task.get("kind") or "build").lower()
    stats = family.get(kind)
    if not stats or not stats.get("total"):
        return 1.0  # no data => neutral
    total = float(stats["total"])
    merged_green = float(stats.get("merged_green", 0))
    retries = float(stats.get("retries", 0))
    rejected = float(stats.get("rejected", 0))
    # success rate: merged-and-stayed-green / total
    success = merged_green / total
    # penalty: retry and rejection rates drag the score down
    retry_drag = 1.0 - min(retries / (total * 3), 0.5)  # cap penalty at 50%
    reject_drag = 1.0 - min(rejected / total, 0.5)
    weight = success * retry_drag * reject_drag
    return max(weight, 0.1)  # floor at 0.1 so nothing is fully zeroed


def score(task, ctx):
    """Expected value per token for one task. Pure + deterministic."""
    project = task.get("project") or ""
    mrr = float((ctx.get("revenue_by_project") or {}).get(project, 0) or 0)
    stats = (ctx.get("outcome_stats") or {}).get(project, {}) or {}
    success_rate = float(stats.get("success_rate", 0.7))
    avg_usd = float(stats.get("avg_usd", 0) or 0)

    s = math.log10(1 + max(0.0, mrr)) * success_rate / (avg_usd + 0.5)

    kind = (task.get("kind") or "").lower()
    delta = (ctx.get("surface_returns") or {}).get(kind)
    if delta and float(delta) > 0:
        s *= 1 + min(float(delta), 100.0) / 100.0

    prompt = (task.get("prompt") or "").lower()
    if kind in BOOST_KINDS and any(w in prompt for w in REVENUE_WORDS):
        s *= 1.5
    if task.get("slug") and task.get("slug") in (ctx.get("approved_slugs") or set()):
        s *= 2.0
    if int(task.get("transient_retries") or 0) >= 2:
        s *= 0.3

    # App-signal adjustments from telemetry_ingest: error spikes boost fix-kind tasks,
    # rising usage boosts feature tasks, dead apps sink. Missing signal = neutral.
    app_signals = (ctx.get("app_signals") or {}).get(project, {})
    if app_signals:
        error_rate = float(app_signals.get("error_rate", 0))
        usage_trend = float(app_signals.get("usage_trend", 0))
        if error_rate > 0.3 and kind in ("bugfix", "fix", "hotfix", "build"):
            s *= 1 + min(error_rate, 1.0)  # up to 2x for high error rates
        if usage_trend > 0.2 and kind in ("build", "feature"):
            s *= 1 + min(usage_trend, 1.0) * 0.5  # up to 1.5x for growing apps
        if usage_trend < -0.5 and error_rate < 0.1:
            s *= 0.5  # dead/declining app with no errors: deprioritize

    # ORCHESTRATOR-FIRST (owner directive): self-improvements to the orchestration layer have no
    # direct MRR but compound across the WHOLE fleet (a better orchestrator ships every app better),
    # so give them a high synthetic EV to rank them at the front of the queue.
    if project in ("beethoven", "orchestrator", "ORCHESTRATOR"):
        s = max(s, 20.0) * float(os.environ.get("ORCH_SELF_IMPROVE_BOOST", "3.0"))
    return s


def thermal_score(task, ctx):
    """Expected merged value per minute. This is the queue's primary heat signal."""
    return thermal_map.score(task, ctx)


def load_ctx():
    """Build the scoring context from db. Every read is fail-soft."""
    ctx = {"revenue_by_project": {}, "surface_returns": {}, "outcome_stats": {},
           "approved_slugs": set()}
    try:
        for r in db.select("app_revenue", {"select": "app,mrr_usd"}) or []:
            ctx["revenue_by_project"][r.get("app")] = float(r.get("mrr_usd") or 0)
    except Exception:
        pass
    try:
        agg = {}
        for r in db.select("outcomes", {"select": "project,usd,integrated",
                                        "limit": "5000"}) or []:
            a = agg.setdefault(r.get("project") or "?", [0.0, 0, 0])
            a[0] += float(r.get("usd") or 0); a[1] += 1
            a[2] += 1 if r.get("integrated") else 0
        for p, (usd, n, ok) in agg.items():
            if n:
                ctx["outcome_stats"][p] = {"success_rate": ok / n, "avg_usd": usd / n}
    except Exception:
        pass
    try:
        agg = {}
        for r in db.select("merge_revenue", {"select": "kind,revenue_delta"}) or []:
            a = agg.setdefault((r.get("kind") or "?").lower(), [0.0, 0])
            a[0] += float(r.get("revenue_delta") or 0); a[1] += 1
        ctx["surface_returns"] = {k: v[0] / v[1] for k, v in agg.items() if v[1]}
    except Exception:
        pass
    try:
        for r in db.select("approvals", {"select": "slug,title,status,radar_tag",
                                         "radar_tag": "not.is.null",
                                         "status": "eq.approved"}) or []:
            slug = r.get("slug") or (r.get("title") or "").rsplit(": ", 1)[-1]
            if slug:
                ctx["approved_slugs"].add(slug)
    except Exception:
        pass
    try:
        ctx["app_signals"] = {}
        for r in db.select("app_telemetry", {"select": "app,error_rate,usage_trend"}) or []:
            app = r.get("app")
            if app:
                ctx["app_signals"][app] = {
                    "error_rate": float(r.get("error_rate") or 0),
                    "usage_trend": float(r.get("usage_trend") or 0),
                }
    except Exception:
        pass
    try:
        import economic_scheduler
        tasks = db.select("tasks", {"select": "*", "state": "eq.QUEUED", "limit": "500"}) or []
        ctx["economic_signals"] = economic_scheduler.predict_revenue_bulk(tasks, ctx)
    except Exception:
        pass
    return ctx


def _scored_queue(limit=500, ctx=None):
    """[(score, task), ...] sorted desc by score (created_at, id break ties)."""
    ctx = ctx if ctx is not None else load_ctx()
    tasks = db.select("tasks", {"select": "*", "state": "eq.QUEUED",
                                "limit": str(limit)}) or []
    names = {}
    try:
        names = {p["id"]: p["name"] for p in
                 db.select("projects", {"select": "id,name"}) or []}
    except Exception:
        pass
    for t in tasks:
        if not t.get("project"):
            t["project"] = names.get(t.get("project_id"), "")
    scored = [(thermal_score(t, ctx), t) for t in tasks]
    scored.sort(key=lambda p: (-p[0], p[1].get("created_at") or "", str(p[1].get("id"))))
    return scored


def rank_queue(limit=500, ctx=None):
    """Task ids for all QUEUED tasks, best expected value first."""
    return [t["id"] for _, t in _scored_queue(limit=limit, ctx=ctx)]


def _has_priority_column():
    try:
        db.select("tasks", {"select": "priority", "limit": "1"})
        return True
    except Exception:
        return False


def apply_ranking(scored=None):
    """Persist the ranking (storage cascade documented in module docstring)."""
    scored = scored if scored is not None else _scored_queue()
    top = scored[:TOP_N]
    if _has_priority_column():
        n = 0
        for idx, (heat, t) in enumerate(top):
            try:
                db.update("tasks", {"id": t["id"]},
                          {"priority": idx + 1,
                           "thermal_score": round(float(heat), 6),
                           "estimated_minutes": round(thermal_map.estimate_minutes(t), 2)})
                n += 1
            except Exception:
                try:
                    db.update("tasks", {"id": t["id"]}, {"priority": idx + 1})
                    n += 1
                except Exception:
                    pass
        return {"storage": "priority", "count": n}
    try:
        ids = [t["id"] for _, t in scored[:CONTROLS_TOP]]
        db.insert("controls", {"key": "thermal_ranking", "value": json.dumps(ids)}, upsert=True)
        return {"storage": "controls", "count": len(ids)}
    except Exception:
        pass
    n = 0
    for idx, (_, t) in enumerate(top):
        try:
            db.update("tasks", {"id": t["id"]},
                      {"confidence": round(max(0.0, 1.0 - idx / float(TOP_N)), 4)})
            n += 1
        except Exception:
            pass
    return {"storage": "confidence", "count": n}


def park_zero_ev(scored=None):
    """Annotate near-zero-EV tasks without blocking them (cap PARK_CAP/run)."""
    scored = scored if scored is not None else _scored_queue()
    parked = 0
    for s, t in scored:
        if parked >= PARK_CAP:
            break
        if s < ZERO_EV and int(t.get("attempt") or 0) >= 2:
            try:
                db.update("tasks", {"id": t["id"]},
                          {"note": PARK_NOTE, "updated_at": "now()"})
                parked += 1
            except Exception:
                pass
    return parked


def shelve_low_ev(scored=None):
    """Annotate already-queued tasks that the pre-queue gate would have refused.

    The gate itself belongs upstream of enqueue, but rows queued BEFORE it existed (and
    rows from producers that do not call it) still sit in the queue dragging the
    queue-velocity PID's integral up. Marking them makes them visible and countable
    without deleting anything: state is untouched, so this is fully reversible and no
    work is destroyed.
    """
    scored = scored if scored is not None else _scored_queue()
    shelved = 0
    for s, t in scored:
        if shelved >= PARK_CAP:
            break
        verdict = should_enqueue(t, ev=s)
        if verdict["enqueue"]:
            continue
        try:
            db.update("tasks", {"id": t["id"]},
                      {"note": LOW_EV_SKIP_NOTE, "updated_at": "now()"})
            shelved += 1
        except Exception:
            pass
    return shelved


def run():
    try:
        scored = _scored_queue()
        applied = apply_ranking(scored)
        parked = park_zero_ev(scored)
        shelved = shelve_low_ev(scored)
        print(f"ev_scheduler: ranked {len(scored)} queued tasks "
              f"(storage={applied['storage']}, wrote {applied['count']}), "
              f"parked {parked}, low-ev shelved {shelved}")
        return {"ranked": len(scored), **applied, "parked": parked,
                "low_ev_shelved": shelved}
    except Exception as e:
        print(f"ev_scheduler: skipped ({e})")
        return {"ranked": 0, "error": str(e)}


if __name__ == "__main__":
    run()
