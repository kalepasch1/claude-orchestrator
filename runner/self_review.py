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

Run: python3 self_review.py        (wire to the 02:00 launchd agent / a Supabase cron)
"""
import os, sys, json, subprocess, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

REVIEW_MODEL = os.environ.get("SELF_REVIEW_MODEL", "claude-opus-4-8")

# ── Infrastructure jobs: exempt from incident penalties ──────────────────────
INFRA_JOBS = frozenset(os.environ.get("ORCH_INFRA_JOBS",
    "kill_switch,pause_arbiter,billing_guard,fleet_stuck_alarm,heartbeat,sentinel,"
    "groom_task_queue,scoreboard,self_review"
).split(","))


def score_job_kpi(job_name):
    """Query the scoreboard/outcomes to return KPI contribution for a job.

    Returns a float: positive means the job contributed to merges/quality,
    zero means neutral, negative means it consumed resources without output.
    Fail-soft: returns 0.0 on any error or missing data.
    """
    if not job_name:
        return 0.0
    try:
        rows = db.select("outcomes", {
            "select": "tests_passed,integrated,usd,slug",
            "slug": f"like.*{job_name}*",
            "order": "created_at.desc",
            "limit": "500",
        }) or []
    except Exception:
        return 0.0
    if not rows:
        return 0.0
    merges = sum(1 for r in rows if r.get("integrated"))
    passes = sum(1 for r in rows if r.get("tests_passed"))
    fails = sum(1 for r in rows if not r.get("tests_passed"))
    spend = sum(float(r.get("usd") or 0) for r in rows)
    n = len(rows)
    # KPI = merge contribution minus cost-weighted failures
    # Each merge is +1.0, each pass-but-not-merged is +0.25, each fail is -0.5
    # Spend penalty: -1 per dollar spent (capped)
    score = (merges * 1.0) + ((passes - merges) * 0.25) + (fails * -0.5) - min(spend, n * 0.5)
    return round(score, 3)


def count_job_incidents(job_name):
    """Count incidents for a job: pause_arbiter trips, revert postmortems, build failures.

    Infrastructure jobs (kill_switch, pause_arbiter, etc.) are exempt and always return 0.
    Fail-soft: returns 0 on any error or partial data.
    """
    if not job_name:
        return 0
    # Infrastructure jobs don't get penalized
    if job_name in INFRA_JOBS:
        return 0
    total = 0
    # 1. Build failures from outcomes
    try:
        rows = db.select("outcomes", {
            "select": "id",
            "slug": f"like.*{job_name}*",
            "tests_passed": "is.false",
            "limit": "1000",
        }) or []
        total += len(rows)
    except Exception:
        pass  # fail-soft: partial data is fine
    # 2. Revert postmortems from postmortems table
    try:
        rows = db.select("postmortems", {
            "select": "id",
            "slug": f"like.*{job_name}*",
            "limit": "500",
        }) or []
        total += len(rows)
    except Exception:
        pass  # fail-soft: table may not exist
    # 3. Pause arbiter trips (controls table, pause events referencing this job)
    try:
        rows = db.select("controls", {
            "select": "key",
            "scope": "eq.global",
            "paused": "is.true",
            "key": f"like.*{job_name}*",
            "limit": "200",
        }) or []
        total += len(rows)
    except Exception:
        pass  # fail-soft: partial data is fine
    return total


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


if __name__ == "__main__":
    run()
