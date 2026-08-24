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

# ── low-EV early exit ─────────────────────────────────────────────────────────────────────
# Refuse worthless work BEFORE it is enqueued, instead of enqueuing it and shelving it later.
# The shelf path is what produces "shelved by queue-velocity PID (low EV, integral too high)"
# — and every shelved task had already been counted into the PID's integral on the way in, so
# the controller was integrating work it then threw away. Refusing at the door removes that
# windup at the source: a task that never entered the queue reports counts_toward_pid=False.
#
# Refusing is STRONGER than parking, so the bar is deliberately harder to trip:
# LOW_EV_THRESHOLD < ZERO_EV, i.e. a task can be park-eligible and still be enqueued.
#: LOW_EV_THRESHOLD / LOW_EV_EARLY_EXIT / EV_FIELDS / the exempt lists are defined ONCE,
#: below, under "TWO SPELLINGS, ONE KNOB". They used to be declared here as well and
#: silently overwritten there, which is how the documented `ORCH_LOW_EV_*` knobs became
#: dead config and how the two exemption call sites drifted apart.
PARK_NOTE = "[ev-low-priority: near-zero expected value — keep queued, run when capacity allows]"
BOOST_KINDS = ("build",)
REVENUE_WORDS = ("revenue", "pricing", "growth", "conversion")


def _env_float_ev(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# --- Low-EV early exit -------------------------------------------------------------
# Refuse negative-EV work BEFORE it is enqueued. Parking (above) annotates work already
# in the queue; this stops it entering. Because a refused task never occupies a queue
# slot, it can never contribute to the queue-velocity PID's integral — the windup
# fix-pid-integral-windup clamps downstream is removed here at the source.
#
# The bar is intentionally STRICTLY LOWER than ZERO_EV: refusing is a stronger action
# than parking, so it must be harder to trigger. Only genuinely negative EV is refused.
# TWO SPELLINGS, ONE KNOB. This block used to redefine LOW_EV_THRESHOLD /
# LOW_EV_EARLY_EXIT under `ORCH_EV_LOW_*` while the block above read `ORCH_LOW_EV_*`.
# The later definition silently won, so an operator raising `ORCH_LOW_EV_THRESHOLD` to
# stop a job being shelved by the queue-velocity PID changed nothing at all — the
# documented mitigation was dead config. Accept BOTH spellings, first one set wins, and
# fail soft on an unparseable value rather than raising at import.
_LOW_EV_THRESHOLD_VARS = ("ORCH_LOW_EV_THRESHOLD", "ORCH_EV_LOW_THRESHOLD")
_LOW_EV_EARLY_EXIT_VARS = ("ORCH_LOW_EV_EARLY_EXIT", "ORCH_EV_LOW_EARLY_EXIT")
_TRUEY = ("true", "1", "yes", "on")


def _first_env(names, default=""):
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return value
    return default


def _coerce_float(raw, default):
    """float(raw), or `default` for anything unparseable/NaN/inf. Never raises."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return default if (math.isnan(value) or math.isinf(value)) else value


def low_ev_threshold():
    """Current enqueue bar, read live so a mid-run env change takes effect."""
    return _coerce_float(_first_env(_LOW_EV_THRESHOLD_VARS), 0.0)


def low_ev_early_exit():
    """Whether the early-exit refusal is armed. Either env spelling works."""
    return _first_env(_LOW_EV_EARLY_EXIT_VARS, "true").strip().lower() in _TRUEY


LOW_EV_THRESHOLD = _coerce_float(_first_env(_LOW_EV_THRESHOLD_VARS), 0.0)
LOW_EV_EARLY_EXIT = _first_env(_LOW_EV_EARLY_EXIT_VARS, "true").strip().lower() in _TRUEY
LOW_EV_SKIP_NOTE = "[ev-low-skip: expected value below the enqueue bar — not scheduled, kept for audit]"
# Field names producers have used for EV, in precedence order.
EV_FIELDS = ("ev", "expected_value", "score", "value")
# Lanes whose value is not EV-expressible: recovery, remediation and evidence work.
# ONE list, shared by both exemption call sites. They previously read two different
# tuples, so a qafix/relfix/buildfix task was exempt on one path and shelved on the
# other — the same job passing or being shelved depending on which check ran.
EXEMPT_KINDS = frozenset({"recovery", "canary", "toolchain-repair", "qafix", "relfix",
                          "buildfix", "deployfix", "rework", "remediation"})
EXEMPT_SLUG_PREFIXES = ("recovery", "recover-", "breach-", "breach-remediation", "canary",
                        "canary-", "qafix", "qafix-", "relfix", "relfix-", "buildfix",
                        "buildfix-", "deployfix", "deployfix-", "toolchain-repair",
                        "rework", "rework-")
# Aliases kept so the older call site cannot drift from the shared definition again.
EV_EXEMPT_KINDS = EXEMPT_KINDS
EV_EXEMPT_PREFIXES = EXEMPT_SLUG_PREFIXES

# Outcome weighting: when ORCH_EV_OUTCOME_WEIGHTING=true, task-family priority is
# weighted by REALIZED outcomes (merged-and-stayed-green rate, retries, human-reject
# rate) rather than flat cost only. Default OFF so current scheduling is byte-identical.
OUTCOME_WEIGHTING_ENABLED = os.environ.get("ORCH_EV_OUTCOME_WEIGHTING", "false").lower() in ("true", "1", "yes")


def task_ev(task):
    """Expected value declared on `task`, or None when it is unknown.

    None means "not measured" and is NEVER treated as zero — a producer that has not
    adopted the EV field must not have every task silently refused.

    Booleans are rejected even though `isinstance(True, int)` is True in Python: `ev=True`
    is a field-type mistake, and reading it as 1.0 would let a typo enqueue work at a
    value nobody assigned.
    """
    if not isinstance(task, dict):
        return None
    for field in EV_FIELDS:
        if field not in task:
            continue
        raw = task[field]
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        # NaN and ±inf are not measurements. NaN in particular compares False against
        # EVERY threshold, so it would silently enqueue as "not below the bar" while
        # poisoning any later arithmetic that touches it.
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    return None


def _ev_exempt(task):
    """True when this task's lane is not EV-expressible (recovery, canary, repair …)."""
    slug = str((task or {}).get("slug") or "").lower()
    kind = str((task or {}).get("kind") or "").lower()
    if kind in EV_EXEMPT_KINDS:
        return True
    return any(slug.startswith(p) for p in EV_EXEMPT_PREFIXES)


def should_enqueue(task, ev=None, threshold=None):
    """Decide whether `task` may enter the queue at all.

    Returns {enqueue, reason, ev, threshold, counts_toward_pid}. `counts_toward_pid` is
    the point of the whole function: it is False EXACTLY when the task was refused, so a
    task that never entered the queue can never be integrated by the queue-velocity PID.
    That windup is what produced hours of "shelved by queue-velocity PID (low EV, integral
    too high)" against work the controller had itself counted on the way in.

    FAILS OPEN everywhere: unknown EV, an exempt lane, the kill switch, or an exception
    inside the gate all enqueue. Refusing work is the destructive direction, so every
    uncertainty resolves toward letting it through.
    """
    threshold = LOW_EV_THRESHOLD if threshold is None else threshold
    verdict = {"enqueue": True, "reason": "", "ev": None,
               "threshold": threshold, "counts_toward_pid": True}

    if not LOW_EV_EARLY_EXIT:
        verdict["reason"] = "low-EV early exit disabled"
        return verdict

    try:
        value = task_ev(task) if ev is None else float(ev)
    except Exception as exc:
        verdict["reason"] = f"gate error ({exc}); enqueuing"
        return verdict

    verdict["ev"] = value

    if value is None:
        verdict["reason"] = "EV unknown; enqueuing"
        return verdict

    if _ev_exempt(task):
        verdict["reason"] = "exempt lane (recovery/evidence/repair); enqueuing"
        return verdict

    if value < threshold:
        slug = str((task or {}).get("slug") or "?")
        verdict.update({"enqueue": False, "counts_toward_pid": False,
                        "reason": f"EV {value} below threshold {threshold}"})
        # Printed, not logged: the refusal must be visible in the producer's own output,
        # and this module already reports through stdout.
        print(f"[ev-scheduler] early exit: {slug} EV={value} < {threshold} — not enqueuing")
        return verdict

    verdict["reason"] = f"EV {value} >= {threshold}"
    return verdict


#: Note written on already-queued rows the gate would have refused. Deliberately distinct
#: from PARK_NOTE: parking means "keep queued, run later", this means "the gate would not
#: have admitted this at all". Conflating them would make the two states unqueryable.
LOW_EV_SKIP_NOTE = ("[ev-low-value: below the enqueue threshold — would not be admitted "
                    "today; left QUEUED for a human to retire or re-scope]")


def shelve_low_ev(scored, threshold=None, cap=None):
    """Mark already-queued rows the gate would now refuse. Returns how many were marked.

    `scored` is [(ev, task), ...] as produced by the ranking pass.

    NEVER changes `state` and never deletes. The gate can only refuse work at the door;
    work already in the queue was admitted under the rules of its day, and silently
    shelving it is exactly the behaviour that produced hours of "shelved by queue-velocity
    PID" against tasks nobody chose to drop. This writes a NOTE so a human can retire or
    re-scope it, and stops at PARK_CAP so one pass can never blanket the queue.

    Fail-soft: a failing update is counted as not-marked rather than raised.
    """
    threshold = LOW_EV_THRESHOLD if threshold is None else threshold
    cap = PARK_CAP if cap is None else cap
    marked = 0
    for value, task in scored or []:
        if marked >= cap:
            break
        try:
            if _ev_exempt(task):
                continue
            if value is None or float(value) >= threshold:
                continue
            db.update("tasks", {"id": task.get("id")}, {"note": LOW_EV_SKIP_NOTE})
            marked += 1
            print(f"[ev-scheduler] low-value: {task.get('slug')} EV={value} — noted, left QUEUED")
        except Exception as exc:
            print(f"[ev-scheduler] could not note {task.get('slug')}: {exc}")
            continue
    return marked


def filter_enqueueable(tasks, threshold=None):
    """Split `tasks` into (keep, skipped) where skipped is [(task, verdict), ...]."""
    keep, skipped = [], []
    for task in tasks or []:
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


#: Recent-outcome sample used for per-project success_rate/avg_usd. Sized at the PostgREST
#: per-response cap on purpose: asking for more than 1,000 in one call silently gets 1,000,
#: so the honest ceiling is stated rather than implied.
OUTCOME_SAMPLE = 1000


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
        # SAMPLE class: per-project success_rate/avg_usd only need a recent window, but it
        # must be a DEFINED window. With no order, PostgREST's 1,000-row response cap made
        # this an arbitrary 1,000 of the outcomes table — so every project's success rate
        # was computed from a non-reproducible sample, and "limit 5000" advertised a depth
        # it never had. created_at.desc matches every other outcomes reader
        # (anomaly, experiment_portfolio, route_value_optimizer).
        for r in db.select("outcomes", {"select": "project,usd,integrated,created_at",
                                        "order": "created_at.desc",
                                        "limit": str(OUTCOME_SAMPLE)}) or []:
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
        # Same FULL SCAN as the ranking sweep: economic signals computed for only the
        # first 500 QUEUED tasks left every other task scored without its revenue signal.
        ctx["economic_signals"] = economic_scheduler.predict_revenue_bulk(queued_tasks(), ctx)
    except Exception:
        pass
    return ctx


#: Deterministic scan order for the QUEUED sweep. Oldest-first matters twice over: offset
#: paging needs a stable order to avoid repeating/skipping rows between pages, and the
#: tasks this scheduler was starving were the OLDEST ones.
QUEUE_SCAN_ORDER = "created_at.asc,id.asc"


def queued_tasks(limit=None, order=QUEUE_SCAN_ORDER):
    """Every QUEUED task (FULL SCAN), or a deterministically-ordered SAMPLE.

    Until 2026-08-06 this was `select("tasks", {"state": "eq.QUEUED", "limit": "500"})`
    with NO order at all, inside a job that runs every 900s to rank and park the queue.
    Measured that day: 1,407 tasks QUEUED, so ~907 of them were invisible to EV ordering
    and to zero-EV parking entirely, and which 500 were seen was not even reproducible
    between cycles. Tasks queued on 2026-08-02 had sat untouched for four days.

    Ranking the queue is a FULL SCAN question — "where does every task belong" — so it
    pages to exhaustion. `limit` is kept for callers that genuinely want a bounded sample
    (rank_queue's top-N callers), and that path now carries the same deterministic order.
    """
    params = {"select": "*", "state": "eq.QUEUED"}
    if limit:
        return db.select("tasks", dict(params, order=order, limit=str(int(limit)))) or []
    return db.select_all("tasks", params, order=order) or []


def scan_coverage(scanned):
    """Report scanned-vs-true queue depth so silent truncation can never return.

    The old window failed silently: it logged "ranked 500 queued tasks" whether the queue
    held 500 or 5,000. Comparing against a server-side count makes a short scan visible
    instead of leaving throughput loss to be inferred from stale tasks days later.
    """
    try:
        depth = db.count("tasks", {"state": "eq.QUEUED"})
    except Exception:
        return {"scanned": scanned, "queue_depth": None, "complete": None}
    complete = depth is not None and scanned >= depth
    if not complete:
        print(f"ev_scheduler: INCOMPLETE SCAN — scored {scanned} of {depth} QUEUED tasks; "
              f"the unscored remainder is invisible to EV ordering and parking", flush=True)
    return {"scanned": scanned, "queue_depth": depth, "complete": complete}


def _self_improve_tier(task):
    """OWNER DIRECTIVE (2026-08-18): the fleet's orchestration-layer self-improvements fill
    IDLE capacity — they must never rank ahead of user-directed product work. Returns 1 for
    self-improvement (claimed last), 0 for user-directed work. Default on; opt out with
    ORCH_USER_TASKS_FIRST=0 to restore pure-EV ordering."""
    if str(os.environ.get("ORCH_USER_TASKS_FIRST", "1")).lower() not in ("1", "true", "yes", "on"):
        return 0
    return 1 if (task.get("project") or "") in ("beethoven", "orchestrator", "ORCHESTRATOR") else 0


def _scored_queue(limit=None, ctx=None):
    """[(score, task), ...] sorted desc by score (created_at, id break ties)."""
    ctx = ctx if ctx is not None else load_ctx()
    tasks = queued_tasks(limit=limit)
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
    scored.sort(key=lambda p: (_self_improve_tier(p[1]), -p[0], p[1].get("created_at") or "", str(p[1].get("id"))))
    return scored


def rank_queue(limit=None, ctx=None):
    """Task ids for all QUEUED tasks, best expected value first.

    Defaults to the full queue: the docstring already promised "all QUEUED tasks" while
    the signature quietly capped it at 500.
    """
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


def task_ev(task):
    """Best-effort read of a producer-supplied expected value off a task row.

    Returns a float, or None when no producer supplied a usable measurement. None is
    deliberately distinct from 0.0: 0.0 is a measured verdict ("we looked, it's worth
    nothing"), None is "nobody looked". Only the former may be refused.
    """
    if not isinstance(task, dict):
        return None
    for field in EV_FIELDS:
        if field not in task:
            continue
        raw = task[field]
        # bools are ints in Python; an `ev=True` is a producer bug, not a measurement.
        if isinstance(raw, bool) or raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isnan(val) or math.isinf(val):
            continue
        return val
    return None


def _is_exempt(task):
    """Recovery/evidence lanes carry value the EV heuristic cannot express."""
    if not isinstance(task, dict):
        return False
    if (task.get("kind") or "").strip().lower() in EXEMPT_KINDS:
        return True
    slug = (task.get("slug") or "").strip().lower()
    return any(slug.startswith(p) for p in EXEMPT_SLUG_PREFIXES)


def should_enqueue(task, ev=None, threshold=None):
    """Gate a task BEFORE it is written to the queue.

    Returns a verdict dict:
      {"enqueue": bool, "reason": str, "ev": float|None, "threshold": float,
       "counts_toward_pid": bool}

    counts_toward_pid mirrors `enqueue`. A task that was never enqueued never occupied a
    queue slot, so the queue-velocity PID must not integrate it — that is the windup this
    gate removes at the source rather than clamping downstream.

    Fails OPEN: an unknown EV, an exempt lane, a disabled kill switch or an exception in
    the gate itself all enqueue. Dropping work is far worse than running a cheap task.
    """
    bar = LOW_EV_THRESHOLD if threshold is None else float(threshold)

    def verdict(enqueue, reason, value):
        return {"enqueue": enqueue, "reason": reason, "ev": value,
                "threshold": bar, "counts_toward_pid": enqueue}

    if not LOW_EV_EARLY_EXIT:
        return verdict(True, "low-EV early exit disabled", ev)
    try:
        value = task_ev(task) if ev is None else ev
        if value is None:
            return verdict(True, "EV unknown — not refusing unmeasured work", None)
        value = float(value)
        if _is_exempt(task):
            return verdict(True, "exempt lane (recovery/evidence) — EV gate not applied", value)
        if value < bar:
            slug = (task or {}).get("slug") if isinstance(task, dict) else task
            print(f"[ev-gate] early exit: not enqueuing {slug} "
                  f"(ev={value} below threshold {bar})")
            return verdict(False, f"EV {value} below threshold {bar}", value)
        return verdict(True, f"EV {value} at or above threshold {bar}", value)
    except Exception as e:
        return verdict(True, f"gate error, failing open: {e}", None)


def filter_enqueueable(tasks, threshold=None):
    """Split tasks into (keep, skipped) where skipped is [(task, verdict), ...]."""
    keep, skipped = [], []
    for t in (tasks or []):
        v = should_enqueue(t, threshold=threshold)
        (keep if v["enqueue"] else skipped).append(t if v["enqueue"] else (t, v))
    return keep, skipped


def shelve_low_ev(scored=None, threshold=None):
    """Annotate ALREADY-QUEUED rows the gate would now refuse. Never changes state.

    The gate above only guards new writes; rows enqueued before it existed still sit in
    the queue inflating the PID's integral. This marks them with LOW_EV_SKIP_NOTE so the
    controller and operators can see them, capped at PARK_CAP per run. It deliberately
    does NOT write `state`: nothing is destroyed, and the annotation is reversible.
    """
    scored = scored if scored is not None else _scored_queue()
    bar = LOW_EV_THRESHOLD if threshold is None else float(threshold)
    marked = 0
    for s, t in scored:
        if marked >= PARK_CAP:
            break
        if s >= bar or _is_exempt(t):
            continue
        try:
            db.update("tasks", {"id": t["id"]},
                      {"note": LOW_EV_SKIP_NOTE, "updated_at": "now()"})
            marked += 1
        except Exception as e:
            print(f"[ev-gate] could not mark {t.get('slug')}: {e}")
    if marked:
        print(f"[ev-gate] marked {marked} already-queued low-EV tasks")
    return marked


def run():
    try:
        scored = _scored_queue()
        coverage = scan_coverage(len(scored))
        applied = apply_ranking(scored)
        parked = park_zero_ev(scored)
        print(f"ev_scheduler: ranked {len(scored)} queued tasks "
              f"(of {coverage['queue_depth']} in queue, complete={coverage['complete']}, "
              f"storage={applied['storage']}, wrote {applied['count']}), parked {parked}")
        return {"ranked": len(scored), **applied, "parked": parked, "coverage": coverage}
    except Exception as e:
        print(f"ev_scheduler: skipped ({e})")
        return {"ranked": 0, "error": str(e)}


if __name__ == "__main__":
    run()
