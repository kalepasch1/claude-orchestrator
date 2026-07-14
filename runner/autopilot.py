#!/usr/bin/env python3
"""
autopilot.py - autonomous queue/improvement operating bot.

This is the coordinator that keeps the orchestrator moving without a human prompt:

  * recovery agent      -> missing-branch / tested-but-unintegrated sweeps
  * blocker agent       -> stale RUNNING, BLOCKED, CONFLICT, TESTFAIL remediation
  * merge/deploy agent  -> canonical merge train, release train, deploy verification
  * ranking agent       -> EV/min ranking + prewarm for the next claimable rows
  * sample agent        -> coder canaries so routing keeps learning
  * dedup agent         -> collapse duplicate queued work under deep backlog
  * improvement agent   -> keep the improve-* queue stocked, cheaply, only when low
  * portfolio agent     -> preserve the original revenue/attention autopilot behavior

Every agent is bounded, fail-soft, and interval-gated through a local state file so this module can
run frequently. It prefers no-spend paths by default; improvement mining uses deterministic fallback
ideas unless ORCH_AUTOPILOT_MODEL_MINING=true is explicitly set.
"""
import collections
import datetime
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MATERIALITY_MRR = float(os.environ.get("AUTOPILOT_MATERIALITY_MRR", "0"))
MAX_DECISIONS_DAY = int(os.environ.get("AUTOPILOT_MAX_DECISIONS", "20"))
SNAPSHOT_LIMIT = int(os.environ.get("AUTOPILOT_SNAPSHOT_LIMIT", "2000"))
IMPROVE_FLOOR = int(os.environ.get("AUTOPILOT_IMPROVE_FLOOR", os.environ.get("IMPROVE_QUEUE_FLOOR", "12")))
RECOVERY_PREFIX = "recover-missing-branch-"
IMPROVE_PREFIX = "improve-"
CANARY_PREFIX = "canary-"
RELEASE_FIX_PREFIXES = ("relfix-", "qafix-", "deployfix-", "buildfix-", "copyfix-")

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
_RUNTIME = os.path.join(_ROOT, ".runtime")
_STATE_FILE = os.path.join(_RUNTIME, "autopilot_state.json")

AGENT_INTERVALS = {
    "resources": int(os.environ.get("AUTOPILOT_RESOURCE_INTERVAL", "60")),
    "portfolio": int(os.environ.get("AUTOPILOT_PORTFOLIO_INTERVAL", "1800")),
    "recovery": int(os.environ.get("AUTOPILOT_RECOVERY_INTERVAL", "120")),
    "blockers": int(os.environ.get("AUTOPILOT_BLOCKER_INTERVAL", "180")),
    "quarantine": int(os.environ.get("AUTOPILOT_QUARANTINE_INTERVAL", "180")),
    "release_blockers": int(os.environ.get("AUTOPILOT_RELEASE_BLOCKER_INTERVAL", "60")),
    "merge_deploy": int(os.environ.get("AUTOPILOT_MERGE_INTERVAL", "180")),
    "ranking": int(os.environ.get("AUTOPILOT_RANK_INTERVAL", "120")),
    "drain_stall": int(os.environ.get("AUTOPILOT_DRAIN_STALL_INTERVAL", "60")),
    "samples": int(os.environ.get("AUTOPILOT_SAMPLE_INTERVAL", "900")),
    "dedup": int(os.environ.get("AUTOPILOT_DEDUP_INTERVAL", "900")),
    "improvements": int(os.environ.get("AUTOPILOT_IMPROVE_INTERVAL", "600")),
    "selfcheck": int(os.environ.get("AUTOPILOT_SELFCHECK_INTERVAL", "600")),
}


class AgentTimeout(RuntimeError):
    pass


def _agent_timeout_seconds(key):
    specific = os.environ.get(f"AUTOPILOT_{key.upper()}_TIMEOUT")
    raw = specific or os.environ.get("AUTOPILOT_AGENT_TIMEOUT", "120")
    try:
        return max(1, int(raw))
    except Exception:
        return 120


def _run_budget_seconds():
    try:
        return max(30, int(os.environ.get("AUTOPILOT_RUN_BUDGET", "240")))
    except Exception:
        return 240


def _call_with_timeout(key, fn):
    seconds = _agent_timeout_seconds(key)
    if not hasattr(signal, "SIGALRM"):
        return fn()
    previous = signal.getsignal(signal.SIGALRM)

    def _handler(signum, frame):
        raise AgentTimeout(f"{key} exceeded {seconds}s")

    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _load_state():
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"agents": {}, "snapshots": []}


def _save_state(state):
    try:
        os.makedirs(_RUNTIME, exist_ok=True)
        with open(_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except OSError:
        pass


def _due(state, key, seconds, force=False):
    if force:
        return True
    last = float((state.get("agents") or {}).get(key, 0) or 0)
    return (time.time() - last) >= seconds


def _mark(state, key):
    state.setdefault("agents", {})[key] = time.time()


def _safe_count(rows, pred):
    return sum(1 for r in rows if pred(r))


def _exact_queue_counts():
    try:
        import queue_counters
        return queue_counters.exact_counts(db_client=db)
    except Exception as e:
        return {"error": str(e)[:300], "states": {}}


def _global_control():
    try:
        rows = db.select("controls", {"select": "paused,reason,updated_by,updated_at",
                                      "scope": "eq.global",
                                      "order": "updated_at.desc",
                                      "limit": "1"}) or []
        if rows:
            row = rows[0]
            paused = bool(row.get("paused"))
            return {
                "paused": paused,
                "reason": (row.get("reason") or "") if paused else "",
                "updated_by": row.get("updated_by") or "",
                "updated_at": row.get("updated_at") or "",
            }
    except Exception as e:
        return {"paused": False, "error": str(e)[:300]}
    return {"paused": False}


def snapshot(limit=SNAPSHOT_LIMIT):
    """Live queue pulse. Read-only and cheap enough to run every autopilot cycle."""
    rows = db.select("tasks", {"select": "id,slug,state,kind,note,updated_at,project_id,remediation_count",
                               "order": "updated_at.desc", "limit": str(limit)}) or []
    states = collections.Counter(r.get("state") for r in rows)
    recovery = collections.Counter(r.get("state") for r in rows
                                   if str(r.get("slug") or "").startswith(RECOVERY_PREFIX))
    improvements = collections.Counter(r.get("state") for r in rows
                                       if str(r.get("slug") or "").startswith(IMPROVE_PREFIX))
    canaries = collections.Counter(r.get("state") for r in rows
                                   if str(r.get("slug") or "").startswith(CANARY_PREFIX))
    release_fixes = collections.Counter(r.get("state") for r in rows
                                        if str(r.get("slug") or "").startswith(RELEASE_FIX_PREFIXES)
                                        or "release_train" in str(r.get("note") or "").lower()
                                        or "vercel" in str(r.get("note") or "").lower())
    try:
        release_rows = db.select("releases", {"select": "project,deploy_status,note,created_at",
                                              "order": "created_at.desc", "limit": "50"}) or []
    except Exception:
        release_rows = []
    recent_failed_releases = [
        r for r in release_rows
        if str(r.get("deploy_status") or "").lower() in ("failed", "rolled_back")
    ]
    verification_blocked_releases = [
        r for r in release_rows
        if str(r.get("deploy_status") or "").lower() == "verification_blocked"
    ]
    blocked = states.get("BLOCKED", 0) + states.get("CONFLICT", 0) + states.get("TESTFAIL", 0)
    exact = _exact_queue_counts()
    exact_states = exact.get("states") or {}
    effective_states = dict(exact_states or states)
    queued = int(exact.get("queued", states.get("QUEUED", 0)) or 0)
    running = int(exact.get("running", states.get("RUNNING", 0)) or 0)
    blocked_like = int(exact.get("blocked_like", blocked) or 0)
    quarantined = int(exact.get("quarantined", states.get("QUARANTINED", 0)) or 0)
    recovery_queued = int(exact.get("recovery_queued", recovery.get("QUEUED", 0)) or 0)
    improvements_queued = int(exact.get("improvements_queued", improvements.get("QUEUED", 0)) or 0)
    canaries_active = int(exact.get("canaries_active", canaries.get("QUEUED", 0) + canaries.get("RUNNING", 0)) or 0)
    release_fix_queued = int(exact.get("release_fix_queued", release_fixes.get("QUEUED", 0)) or 0)
    release_fix_running = int(exact.get("release_fix_running", release_fixes.get("RUNNING", 0)) or 0)
    global_control = _global_control()
    snap = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "sampled": len(rows),
        "states": effective_states,
        "sample_states": dict(states),
        "recovery": dict(recovery),
        "improvements": dict(improvements),
        "canaries": dict(canaries),
        "release_fixes": dict(release_fixes),
        "sampled_queued": states.get("QUEUED", 0),
        "sampled_running": states.get("RUNNING", 0),
        "sampled_blocked_like": blocked,
        "exact_queue": exact,
        "total_tasks": exact.get("total_tasks", len(rows)),
        "unknown_state_total": exact.get("unknown_state_total", 0),
        "queued": queued,
        "running": running,
        "blocked_like": blocked_like,
        "quarantined": quarantined,
        "recovery_queued": recovery_queued,
        "improvements_queued": improvements_queued,
        "canaries_active": canaries_active,
        "release_fix_queued": release_fix_queued,
        "release_fix_running": release_fix_running,
        "global_paused": bool(global_control.get("paused")),
        "global_pause_reason": global_control.get("reason", ""),
        "global_pause_by": global_control.get("updated_by", ""),
        "global_pause_at": global_control.get("updated_at", ""),
        "recent_failed_releases": len(recent_failed_releases),
        "verification_blocked_releases": len(verification_blocked_releases),
        "deep_backlog": queued >= int(os.environ.get("AUTOPILOT_DEEP_BACKLOG", "500")),
    }
    return snap


def _record_snapshot(state, snap, agents):
    state.setdefault("snapshots", []).append({
        "at": snap["generated_at"],
        "queued": snap["queued"],
        "running": snap["running"],
        "blocked_like": snap["blocked_like"],
        "recovery_queued": snap["recovery_queued"],
        "improvements_queued": snap["improvements_queued"],
        "release_fix_queued": snap.get("release_fix_queued", 0),
        "recent_failed_releases": snap.get("recent_failed_releases", 0),
        "verification_blocked_releases": snap.get("verification_blocked_releases", 0),
        "sampled": snap.get("sampled", 0),
        "total_tasks": snap.get("total_tasks", 0),
        "sampled_queued": snap.get("sampled_queued", 0),
        "unknown_state_total": snap.get("unknown_state_total", 0),
        "agents": {a["agent"]: a["ok"] for a in agents},
        "global_paused": snap.get("global_paused", False),
        "global_pause_by": snap.get("global_pause_by", ""),
    })
    state["snapshots"] = state["snapshots"][-24:]
    try:
        db.insert("controls", {"key": "queue_autopilot",
                               "value": json.dumps({"snapshot": snap, "agents": agents}, default=str),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass


def _run_agent(state, key, label, fn, force=False):
    if not _due(state, key, AGENT_INTERVALS.get(key, 300), force=force):
        return {"agent": label, "ok": True, "skipped": "interval"}
    try:
        result = _call_with_timeout(key, fn)
        _mark(state, key)
        return {"agent": label, "ok": True, "result": result}
    except AgentTimeout as e:
        _mark(state, key)
        return {"agent": label, "ok": False, "timeout": True, "error": str(e)}
    except Exception as e:
        _mark(state, key)
        return {"agent": label, "ok": False, "error": str(e)[:500]}


def portfolio_attention_agent():
    """Original autopilot behavior: refresh economic weights and clear sub-threshold material cards."""
    try:
        import portfolio_governor
        portfolio_governor.run(apply=True)
    except Exception as e:
        print(f"autopilot: governor step skipped ({e})")
    mrr = {r["app"]: float(r.get("mrr_usd") or 0)
           for r in (db.select("app_revenue", {"select": "*"}) or [])}
    cards = db.select("approvals", {"select": "id,kind,project,radar_tag,title",
                                    "status": "eq.pending", "kind": "eq.material",
                                    "limit": "500"}) or []
    deferrable = [c for c in cards if not c.get("radar_tag")
                  and "legal" not in (c.get("title") or "").lower()]
    deferrable.sort(key=lambda c: mrr.get(c.get("project"), 0), reverse=True)
    deferred = 0
    for c in deferrable[MAX_DECISIONS_DAY:]:
        db.update("approvals", {"id": c["id"]},
                  {"status": "approved", "decided_by": "autopilot-sub-threshold",
                   "decided_at": "now()"})
        deferred += 1
    return {"kept": min(len(deferrable), MAX_DECISIONS_DAY), "cleared": deferred}


def resource_agent():
    import resource_governor
    return resource_governor.govern()


def drain_stall_agent(snap):
    """Recover the exact overnight failure: deep queue, no runners, auto pause left on."""
    out = {
        "queued": snap.get("queued", 0),
        "running": snap.get("running", 0),
        "global_paused": snap.get("global_paused", False),
        "global_pause_by": snap.get("global_pause_by", ""),
        "global_pause_reason": snap.get("global_pause_reason", "")[:240],
    }
    reason = str(snap.get("global_pause_reason") or "").lower()
    by = str(snap.get("global_pause_by") or "")
    if snap.get("global_paused"):
        if by == "billing_guard" or "billing_guard" in reason or "api key" in reason:
            try:
                import billing_guard
                out["billing_guard"] = billing_guard.run()
            except Exception as e:
                out["billing_guard_error"] = str(e)[:300]
        if by in ("governor", "claude_cli") or any(k in reason for k in ("low-memory", "cost circuit", "call cap", "$ cap", "hourly")):
            try:
                import resource_governor
                out["resource_governor"] = resource_governor.govern()
            except Exception as e:
                out["resource_governor_error"] = str(e)[:300]
    if snap.get("queued", 0) and not snap.get("running", 0):
        try:
            import queue_janitor
            out["queue_janitor"] = queue_janitor.run()
        except Exception as e:
            out["queue_janitor_error"] = str(e)[:300]
    return out


def recovery_agent():
    import integration_sweeper
    limit = int(os.environ.get("AUTOPILOT_SWEEP_LIMIT", "250"))
    return integration_sweeper.sweep(limit=limit, run_train=True)


def blocker_agent():
    out = {}
    try:
        import queue_janitor
        out["janitor"] = queue_janitor.run()
    except Exception as e:
        out["janitor_error"] = str(e)[:300]
    try:
        import auto_remediate
        out["remediate"] = auto_remediate.run(limit=int(os.environ.get("AUTOPILOT_REMEDIATE_LIMIT", "500")))
    except Exception as e:
        out["remediate_error"] = str(e)[:300]
    try:
        import blocker_quarantine
        out["quarantine"] = blocker_quarantine.run(limit=int(os.environ.get("AUTOPILOT_QUARANTINE_LIMIT", "120")))
    except Exception as e:
        out["quarantine_error"] = str(e)[:300]
    return out


def release_blocker_agent():
    """Hot lane for release blockers: warm, retry gated train, then verify deployments."""
    out = {}
    old_prewarm = os.environ.get("PREWARM_N")
    try:
        os.environ["PREWARM_N"] = str(max(int(os.environ.get("PREWARM_N", "4")), 12))
        import prewarm
        out["prewarm"] = prewarm.run()
    except Exception as e:
        out["prewarm_error"] = str(e)[:300]
    finally:
        if old_prewarm is None:
            os.environ.pop("PREWARM_N", None)
        else:
            os.environ["PREWARM_N"] = old_prewarm
    try:
        old_min_batch = os.environ.get("RELEASE_MIN_BATCH")
        old_interval = os.environ.get("RELEASE_INTERVAL_HOURS")
        flush_now = os.environ.get("AUTOPILOT_RELEASE_BLOCKER_FLUSH", "false").lower() in ("1", "true", "yes", "on")
        if flush_now:
            os.environ["RELEASE_MIN_BATCH"] = "1"
            os.environ["RELEASE_INTERVAL_HOURS"] = "0"
        import release_train
        if flush_now:
            release_train.MIN_BATCH = 1
            release_train.RELEASE_INTERVAL_HOURS = 0
        out["release_train"] = release_train.run()
    except Exception as e:
        out["release_train_error"] = str(e)[:300]
    finally:
        if old_min_batch is None:
            os.environ.pop("RELEASE_MIN_BATCH", None)
        else:
            os.environ["RELEASE_MIN_BATCH"] = old_min_batch
        if old_interval is None:
            os.environ.pop("RELEASE_INTERVAL_HOURS", None)
        else:
            os.environ["RELEASE_INTERVAL_HOURS"] = old_interval
        try:
            import release_train
            release_train.MIN_BATCH = int(os.environ.get("RELEASE_MIN_BATCH", os.environ.get("ORCH_RELEASE_BATCH_MIN", "10")))
            release_train.RELEASE_INTERVAL_HOURS = float(os.environ.get("RELEASE_INTERVAL_HOURS", os.environ.get("ORCH_RELEASE_INTERVAL_HOURS", "6")))
        except Exception:
            pass
    try:
        import deploy_verify
        out["deploy_verify"] = deploy_verify.run()
    except Exception as e:
        out["deploy_verify_error"] = str(e)[:300]
    return out


def merge_deploy_agent():
    out = {}
    try:
        import merge_train
        out["merge_train"] = merge_train.train_run()
    except Exception as e:
        out["merge_train_error"] = str(e)[:300]
    hot_lane_owns_release = os.environ.get(
        "AUTOPILOT_RELEASE_TRAIN_ONLY_HOTLANE", "true"
    ).lower() in ("1", "true", "yes", "on")
    if (not hot_lane_owns_release
            and os.environ.get("AUTOPILOT_RUN_RELEASE_TRAIN", "true").lower() in ("1", "true", "yes", "on")):
        try:
            import release_train
            out["release_train"] = release_train.run()
        except Exception as e:
            out["release_train_error"] = str(e)[:300]
    if os.environ.get("AUTOPILOT_RUN_DEPLOY_VERIFY", "true").lower() in ("1", "true", "yes", "on"):
        try:
            import deploy_verify
            out["deploy_verify"] = deploy_verify.run()
        except Exception as e:
            out["deploy_verify_error"] = str(e)[:300]
    return out


def ranking_agent():
    out = {}
    try:
        import ev_scheduler
        out["ev_scheduler"] = ev_scheduler.run()
    except Exception as e:
        out["ev_scheduler_error"] = str(e)[:300]
    if os.environ.get("AUTOPILOT_PREWARM", "true").lower() in ("1", "true", "yes", "on"):
        try:
            import prewarm
            out["prewarm"] = prewarm.run()
        except Exception as e:
            out["prewarm_error"] = str(e)[:300]
    return out


def sample_agent():
    out = {}
    try:
        import route_evidence
        out["route_evidence"] = route_evidence.run()
    except Exception as e:
        out["route_evidence_error"] = str(e)[:300]
    try:
        import coder_canary
        out["coder_canary"] = coder_canary.run(limit_per_coder=1)
    except Exception as e:
        out["coder_canary_error"] = str(e)[:300]
    return out


def dedup_agent():
    import task_dedup
    return task_dedup.apply()


def improvement_agent():
    env = {}
    if os.environ.get("ORCH_AUTOPILOT_MODEL_MINING", "false").lower() not in ("1", "true", "yes", "on"):
        env["IMPROVE_USE_MODEL"] = "false"
    env["IMPROVE_QUEUE_FLOOR"] = str(IMPROVE_FLOOR)
    old = {k: os.environ.get(k) for k in env}
    try:
        os.environ.update(env)
        import improvement_miner
        return improvement_miner.run()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def selfcheck_agent():
    import startup_selfcheck
    return startup_selfcheck.run("autopilot")


def run(force=False):
    state = _load_state()
    snap = snapshot()
    agents = []
    started = time.time()

    def add_agent(key, label, fn):
        elapsed = time.time() - started
        budget = _run_budget_seconds()
        if elapsed >= budget:
            agents.append({"agent": label, "ok": False, "skipped": "run_budget",
                           "elapsed_s": int(elapsed), "budget_s": budget})
            return
        agents.append(_run_agent(state, key, label, fn, force=force))

    if snap.get("global_paused") or (snap.get("queued", 0) and not snap.get("running", 0)):
        add_agent("drain_stall", "drain_stall", lambda: drain_stall_agent(snap),)

    add_agent("resources", "resources", resource_agent)

    if snap["recovery_queued"] or snap["states"].get("DONE", 0) or snap["states"].get("BLOCKED", 0):
        add_agent("recovery", "recovery", recovery_agent)

    if snap.get("release_fix_queued") or snap.get("release_fix_running") or snap.get("recent_failed_releases"):
        add_agent("release_blockers", "release_blockers", release_blocker_agent)

    if snap["states"].get("DONE", 0) or snap["states"].get("MERGED", 0):
        add_agent("merge_deploy", "merge_deploy", merge_deploy_agent)

    if snap["queued"]:
        add_agent("ranking", "ranking", ranking_agent)

    if snap["blocked_like"] or snap["running"] or snap["states"].get("BLOCKED", 0):
        add_agent("blockers", "blockers", blocker_agent)

    if snap["deep_backlog"]:
        add_agent("dedup", "dedup", dedup_agent)

    if snap["canaries_active"] < int(os.environ.get("AUTOPILOT_MIN_ACTIVE_CANARIES", "4")):
        add_agent("samples", "samples", sample_agent)

    if snap["improvements_queued"] < IMPROVE_FLOOR:
        add_agent("improvements", "improvements", improvement_agent)

    if os.environ.get("AUTOPILOT_INLINE_SELFCHECK", "false").lower() in ("1", "true", "yes", "on"):
        add_agent("selfcheck", "selfcheck", selfcheck_agent)
    else:
        agents.append({"agent": "selfcheck", "ok": True, "skipped": "external_scheduler"})
    add_agent("portfolio", "portfolio", portfolio_attention_agent)
    _record_snapshot(state, snap, agents)
    _save_state(state)
    ok = sum(1 for a in agents if a.get("ok"))
    fail = len(agents) - ok
    print(f"autopilot: queue={snap['queued']} running={snap['running']} "
          f"sampled={snap.get('sampled', 0)}/{snap.get('total_tasks', snap.get('sampled', 0))} "
          f"blocked={snap['blocked_like']} recovery={snap['recovery_queued']} "
          f"paused={snap.get('global_paused', False)} "
          f"release_fix={snap.get('release_fix_queued', 0)} "
          f"improve={snap['improvements_queued']} agents_ok={ok} agents_fail={fail}")
    return {"snapshot": snap, "agents": agents}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
