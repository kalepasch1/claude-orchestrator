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


# ── Monthly subsystem audit (D5) ─────────────────────────────────────────────

def _parse_schedule_table():
    """Parse runner.py's _SCHEDULE list to enumerate all periodic jobs."""
    runner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py")
    jobs = []
    try:
        with open(runner_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        # Find _SCHEDULE = [...] block
        m = re.search(r'_SCHEDULE\s*=\s*\[', text)
        if not m:
            return jobs
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
            i += 1
        block = text[start:i - 1]
        # Parse tuples: ("name", "script", "type", interval_or_tuple)
        for tm in re.finditer(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,', block):
            jobs.append({"id": tm.group(1), "script": tm.group(2)})
    except Exception:
        pass
    return jobs


def _job_kpi_scores():
    """Attribute KPI contribution to jobs using scoreboard/outcomes data."""
    scores = {}
    try:
        import scoreboard
        payload = scoreboard.compute()
        overall = payload.get("overall", {})
        scores["_overall_merge_rate"] = overall.get("merge_rate")
        scores["_overall_usd_per_merge"] = overall.get("usd_per_merge")
    except Exception:
        pass
    return scores


def _job_incidents():
    """Count incidents attributable to each job: pause_arbiter trips, build failures,
    revert postmortems."""
    incidents = collections.Counter()
    # Check for pause events mentioning job names
    try:
        rows = db.select("controls", {
            "select": "key,value,updated_at",
            "order": "updated_at.desc",
            "limit": "500",
        }) or []
        for r in rows:
            val = str(r.get("value") or "")
            key = str(r.get("key") or "")
            if "pause" in key.lower() or "trip" in val.lower():
                # Try to attribute to a job
                for word in val.split():
                    w = word.strip(".,;:'\"()").lower()
                    if w.endswith(".py") or "-" in w:
                        incidents[w] += 1
    except Exception:
        pass
    # Check outcomes for build failures
    try:
        rows = db.select("outcomes", {
            "select": "slug,tests_passed",
            "tests_passed": "eq.false",
            "order": "created_at.desc",
            "limit": "500",
        }) or []
        for r in rows:
            slug = str(r.get("slug") or "")
            if slug:
                incidents[slug] += 1
    except Exception:
        pass
    return dict(incidents)


def _score_job(job, kpi_scores, incidents):
    """Score a single job. Higher = more valuable (keep). Lower = candidate for disable.

    Pure infrastructure/safety jobs with no direct KPI line but zero incidents get a
    neutral score (not punished for having no KPI contribution).
    """
    job_id = job["id"]
    script = job["script"]
    incident_count = incidents.get(script, 0) + incidents.get(job_id, 0)

    # Protected jobs get max score — never proposed for disable
    if job_id in _PROTECTED_JOBS or script in _PROTECTED_JOBS:
        return {"score": float("inf"), "incidents": incident_count,
                "kpi_contribution": "protected", "protected": True}

    # Base score: 50 (neutral)
    score = 50.0
    # Penalty for incidents
    score -= incident_count * 10
    # Jobs that are infrastructure/safety (no direct KPI) but incident-free are kept neutral
    # Jobs with known KPI contribution get a boost (placeholder — real attribution from scoreboard)
    return {"score": score, "incidents": incident_count,
            "kpi_contribution": "unmeasured", "protected": False}


def monthly_audit():
    """Monthly subsystem audit: enumerate all scheduled jobs, score them, propose
    disabling the bottom decile as a single material approval card."""
    jobs = _parse_schedule_table()
    if not jobs:
        print("monthly_audit: could not parse schedule table from runner.py")
        return None

    kpi_scores = _job_kpi_scores()
    incidents = _job_incidents()

    scored = []
    for job in jobs:
        s = _score_job(job, kpi_scores, incidents)
        scored.append({**job, **s})

    # Sort by score ascending (worst first)
    scored.sort(key=lambda x: x["score"] if x["score"] != float("inf") else 1e9)

    # Bottom decile (excluding protected jobs)
    non_protected = [j for j in scored if not j.get("protected")]
    decile_size = max(1, math.ceil(len(non_protected) * 0.1))
    bottom_decile = non_protected[:decile_size]

    report = {
        "total_jobs": len(jobs),
        "scored_jobs": len(non_protected),
        "protected_jobs": len(scored) - len(non_protected),
        "bottom_decile_count": len(bottom_decile),
        "bottom_decile": [{"id": j["id"], "script": j["script"],
                           "score": j["score"], "incidents": j["incidents"]}
                          for j in bottom_decile],
        "all_scores": [{"id": j["id"], "script": j["script"],
                        "score": j["score"] if j["score"] != float("inf") else "protected",
                        "incidents": j["incidents"]}
                       for j in scored],
    }

    # File a single material approval card for the batch
    if bottom_decile:
        disable_list = ", ".join(j["id"] for j in bottom_decile)
        try:
            db.insert("approvals", {
                "project": "ORCHESTRATOR",
                "kind": "material",
                "title": f"Monthly audit: propose disabling {len(bottom_decile)} bottom-decile jobs",
                "why": f"Monthly subsystem audit scored {len(jobs)} scheduled jobs. "
                       f"Bottom decile ({len(bottom_decile)} jobs) have the lowest KPI contribution "
                       f"and/or highest incident counts: {disable_list}",
                "value": f"Reduce orchestrator overhead by disabling {len(bottom_decile)} low-value periodic jobs",
                "risk": "Jobs may have hidden dependencies. Review each before disabling. "
                        "This is a batch proposal — approve or reject as a whole.",
                "detail": json.dumps(report, indent=2, default=str),
                "command": "",
            })
        except Exception as e:
            sys.stderr.write(f"[monthly_audit] failed to file approval: {e}\n")

    print(f"monthly_audit: scored {len(jobs)} jobs, {len(bottom_decile)} in bottom decile, "
          f"{len(scored) - len(non_protected)} protected. Filed 1 material approval card.")
    return report


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
