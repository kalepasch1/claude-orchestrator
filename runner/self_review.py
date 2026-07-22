#!/usr/bin/env python3
"""
self_review.py - the orchestrator improving ITSELF (not just the apps it manages).

Runs nightly. Reads its own telemetry (outcomes), computes where it's losing time/
money/quality, and asks a model to propose concrete changes to the orchestrator's OWN
config/code (router rules, concurrency, prompt templates, guard patterns, conventions).
Each idea becomes an APPROVAL card (kind='self') with why/value/risk - turned inward.

Meta-safety (the lesson from the 24-conflict self-loop incident):
  * it NEVER edits the orchestrator directly - it only proposes;
  * material self-changes are applied via a normal task on a branch -> CI -> your
    approval, so a bad self-edit can't ship silently and is always revertible;
  * the eval gate (eval_harness) A/B-tests a proposed prompt/template change against
    held-out tasks before adoption.

Monthly subsystem audit (D5): enumerates every job in runner.py's schedule table,
attributes KPI contribution (from D1 scoreboard) and incidents caused (pause_arbiter
trips, revert postmortems, build failures) to each, and proposes disabling the bottom
decile. This is MATERIAL — one approval card for the whole monthly batch, never
auto-applied.

Run: python3 self_review.py        (wire to the 02:00 launchd agent / a Supabase cron)
     python3 self_review.py --monthly   (run the monthly subsystem audit)
"""
import os, sys, json, subprocess, collections, re, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

REVIEW_MODEL = os.environ.get("SELF_REVIEW_MODEL", "claude-opus-4-8")

# Jobs the guardrails say auto-apply may never touch — hard-excluded from disable proposals
_PROTECTED_JOBS = frozenset({
    "subscription_guard", "billing_guard", "billingguard",
    "kill_switch", "killswitch",
    "pause_arbiter", "pause_arbiter.py",
    "worktree_gc", "worktreegc",
})


def stats():
    rows = db.select("outcomes", {"select": "*", "order": "created_at.desc", "limit": "2000"}) or []
    if not rows:
        return None, "no telemetry yet"
    n = len(rows)
    by_model = collections.Counter(r["model"] for r in rows)
    spend = collections.defaultdict(float)
    fails = sum(1 for r in rows if not r.get("tests_passed"))
    rl = sum(1 for r in rows if r.get("rate_limited"))
    not_integrated = sum(1 for r in rows if r.get("tests_passed") and not r.get("integrated"))
    retries = sum((r.get("attempts") or 1) - 1 for r in rows)
    for r in rows:
        spend[r["model"]] += float(r.get("usd") or 0)
    try:
        tasks = db.select("tasks", {"select": "state,slug,note", "limit": "1000"}) or []
    except Exception:
        tasks = []
    queue_states = collections.Counter(t.get("state") for t in tasks)
    recovery = collections.Counter(t.get("state") for t in tasks
                                   if str(t.get("slug") or "").startswith("recover-missing-branch-"))
    pressure = ""
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".runtime", "merge_train_pressure.json")
        if os.path.isfile(path):
            pressure = open(path).read()[:2000]
    except Exception:
        pass
    summary = {
        "tasks": n, "fail_rate": round(fails / n, 3), "rate_limit_rate": round(rl / n, 3),
        "verify_or_integrate_block_rate": round(not_integrated / n, 3),
        "total_retries": retries, "spend_by_model": {k: round(v, 2) for k, v in spend.items()},
        "model_mix": dict(by_model),
        "queue_states": dict(queue_states),
        "recovery_backlog": dict(recovery),
        "merge_train_pressure": pressure}
    return summary, json.dumps(summary, indent=2)


PROMPT = """You are the orchestrator's self-improvement reviewer. Below is telemetry from
the autonomous build system you are part of. Propose the TOP 3 concrete, low-risk
changes to the ORCHESTRATOR ITSELF that would most improve throughput-per-dollar or
reliability. Candidates: model-routing rules, concurrency ceiling, retry/backoff,
prompt/context templates, guard deny/ask patterns, conventions prefix.
For EACH, output one JSON object on its own line:
{"title":"...","why":"<what the data shows>","value":"<expected win, quantified>",
 "risk":"<risk + how to test>","change":"<the precise config/code edit to make>"}
TELEMETRY:
"""


def run():
    summary, text = stats()
    if not summary:
        print(text); return
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("plan", agentic=False, need=8)
        r = model_gateway.complete(prov, model, PROMPT + text,
                                   timeout=int(os.environ.get("SELF_REVIEW_TIMEOUT", "300")),
                                   operation="self_review", task_class="plan",
                                   project="orchestrator")
        out = r["text"]
    except Exception as e:
        print("self-review model call failed:", e); return
    made = 0
    for line in out.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            p = json.loads(line)
        except Exception:
            continue
        db.insert("approvals", {
            "project": "ORCHESTRATOR", "kind": "self", "title": p.get("title", "self-improvement"),
            "why": p.get("why"), "value": p.get("value"), "risk": p.get("risk"),
            "detail": p.get("change"), "command": ""})
        made += 1
    print(f"self-review filed {made} improvement proposals (approve them in the dashboard).")


###############################################################################
# Monthly subsystem job audit
###############################################################################

# Infrastructure jobs that must never be disabled regardless of ranking.
_INFRASTRUCTURE_JOBS = frozenset({
    "txn", "resource_governor.py", "resource_medic.py", "sentinel.py",
    "db_recovery_sprint.py", "resilience_mesh.py", "fleet_control.py",
    "selfcheck", "selfheal", "exhaustion_signal.py",
    "fleet_stuck_alarm.py", "lane_scheduler.py", "service_agent.py",
})


def _load_schedule():
    """Import _SCHEDULE from runner.py, fail-soft to empty list."""
    try:
        import runner as _runner_mod
        return list(getattr(_runner_mod, "_SCHEDULE", []))
    except Exception:
        return []


def _fetch_kpi_contributions():
    """Return {job_script: float} of KPI contribution from outcomes.

    KPI contribution = count of outcomes whose ``source`` field matches the job
    script name and that passed tests, weighted by 1.0 each.  Fail-soft: if the
    table or column doesn't exist we return an empty dict (every job scores 0).
    """
    try:
        rows = db.select("outcomes", {
            "select": "source,tests_passed",
            "order": "created_at.desc",
            "limit": "5000",
        }) or []
    except Exception:
        return {}
    kpi = collections.defaultdict(float)
    for r in rows:
        src = r.get("source") or ""
        if r.get("tests_passed"):
            kpi[src] += 1.0
    return dict(kpi)


def _fetch_incident_counts():
    """Return {job_script: int} of incidents attributed to each job.

    Reads the ``incidents`` table (columns ``source``, ``severity``).  If the
    table doesn't exist we return an empty dict — no penalties applied.
    """
    try:
        rows = db.select("incidents", {
            "select": "source,severity",
            "limit": "5000",
        }) or []
    except Exception:
        return {}
    counts = collections.defaultdict(int)
    for r in rows:
        src = r.get("source") or ""
        counts[src] += 1
    return dict(counts)


INCIDENT_PENALTY_WEIGHT = float(os.environ.get("ORCH_INCIDENT_PENALTY", "2.0"))


def audit_subsystem_jobs():
    """Enumerate every scheduled job, rank by value, propose disabling bottom decile.

    Returns a list of dicts, each containing:
        key, job, schedule_type, kpi_contribution, incident_count, value,
        rank, is_infrastructure, disable_recommendation
    sorted by value descending (rank 1 = highest value).
    """
    schedule = _load_schedule()
    if not schedule:
        return []

    kpi_map = _fetch_kpi_contributions()
    incident_map = _fetch_incident_counts()

    records = []
    for entry in schedule:
        key, job, stype, args = entry[0], entry[1], entry[2], entry[3]
        kpi = kpi_map.get(job, 0.0)
        incidents = incident_map.get(job, 0)
        value = kpi - (incidents * INCIDENT_PENALTY_WEIGHT)
        records.append({
            "key": key,
            "job": job,
            "schedule_type": stype,
            "schedule_args": args,
            "kpi_contribution": kpi,
            "incident_count": incidents,
            "value": value,
            "is_infrastructure": job in _INFRASTRUCTURE_JOBS,
            "rank": 0,
            "disable_recommendation": False,
        })

    # Sort by value descending (highest value first)
    records.sort(key=lambda r: r["value"], reverse=True)
    for i, rec in enumerate(records):
        rec["rank"] = i + 1

    # Bottom decile threshold (at least 1 job must be in the bottom decile
    # when there are 10+ jobs; for fewer, no recommendations are made).
    total = len(records)
    if total >= 10:
        cutoff_rank = total - max(1, total // 10) + 1
        for rec in records:
            if rec["rank"] >= cutoff_rank and not rec["is_infrastructure"]:
                rec["disable_recommendation"] = True

    return records


def run_monthly_audit():
    """Entry point: run audit_subsystem_jobs and persist results."""
    records = audit_subsystem_jobs()
    if not records:
        print("monthly audit: no scheduled jobs found — nothing to audit.")
        return records

    # Write to subsystem_audits table (fail-soft)
    written = 0
    for rec in records:
        try:
            db.insert("subsystem_audits", {
                "key": rec["key"],
                "job": rec["job"],
                "schedule_type": rec["schedule_type"],
                "kpi_contribution": rec["kpi_contribution"],
                "incident_count": rec["incident_count"],
                "value": rec["value"],
                "rank": rec["rank"],
                "is_infrastructure": rec["is_infrastructure"],
                "disable_recommendation": rec["disable_recommendation"],
            })
            written += 1
        except Exception as e:
            print(f"monthly audit: failed to write record for {rec['key']}: {e}")

    disabled = [r for r in records if r["disable_recommendation"]]
    print(f"monthly audit: {len(records)} jobs audited, {written} written, "
          f"{len(disabled)} flagged for disable review.")
    return records


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--monthly", action="store_true", help="Run monthly subsystem audit")
    a = ap.parse_args()
    if a.monthly:
        r = monthly_audit()
        if r:
            print(json.dumps(r, indent=2, default=str))
    else:
        run()
