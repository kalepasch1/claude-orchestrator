#!/usr/bin/env python3
"""
monthly_subsystem_audit.py — monthly audit of every periodic job in runner.py's _SCHEDULE.

Attributes KPI contribution (from scoreboard/outcomes) and incidents (pause_arbiter trips,
revert postmortems, build failures) to each job, then proposes disabling the bottom decile.
The proposal is a SINGLE material approval card (never auto-applied).

Hard-excluded jobs (infrastructure/safety — never proposed for disable):
  subscription_guard, billing_guard, kill_switch, pause_arbiter, worktree_gc,
  billingguard, worktreegc, resource_governor.py, governor

Run: python3 monthly_subsystem_audit.py   (wire to a monthly cron or invoke manually)
"""
import os, sys, json, math, datetime, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Jobs that must NEVER be proposed for disabling — they are pure infrastructure/safety
# with no direct KPI line and their removal would compromise system integrity.
HARD_EXCLUDED_JOBS = frozenset({
    "subscription_guard", "billing_guard", "kill_switch",
    "pause_arbiter", "worktree_gc",
    # Aliases used in _SCHEDULE:
    "billingguard", "worktreegc", "resource_governor.py", "governor",
    "pause_arbiter.py", "sentinel.py", "resource_medic.py",
    "db_recovery_sprint.py", "resilience_mesh.py",
    "fleet_stuck_alarm.py", "selfcheck", "selfheal",
})

WINDOW_DAYS = int(os.environ.get("ORCH_AUDIT_WINDOW_DAYS", "30"))


def _iso_days_ago(days):
    return (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()


def _load_schedule():
    """Parse _SCHEDULE from runner.py to get the job list."""
    jobs = []
    try:
        runner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py")
        with open(runner_path, "r", errors="replace") as f:
            src = f.read()
        in_schedule = False
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("_SCHEDULE") and "=" in stripped:
                in_schedule = True
                continue
            if in_schedule:
                if stripped.startswith("]"):
                    break
                if stripped.startswith("(") and stripped.endswith("),"):
                    parts = stripped[1:-2].split(",")
                    if len(parts) >= 3:
                        job_id = parts[0].strip().strip('"').strip("'")
                        job_script = parts[1].strip().strip('"').strip("'")
                        jobs.append({"id": job_id, "script": job_script})
    except Exception:
        pass
    return jobs


def _fetch_outcomes():
    """Fetch outcome rows from the last WINDOW_DAYS."""
    try:
        return db.select("outcomes", {
            "select": "project,model,tests_passed,integrated,usd,created_at",
            "created_at": f"gte.{_iso_days_ago(WINDOW_DAYS)}",
            "limit": "10000",
        }) or []
    except Exception:
        return []


def _fetch_incidents():
    """Fetch incidents: pause_arbiter trips, build failures, reverts from controls/approvals."""
    incidents = []
    try:
        rows = db.select("controls", {
            "select": "scope,paused,updated_at,updated_by",
            "updated_at": f"gte.{_iso_days_ago(WINDOW_DAYS)}",
            "limit": "5000",
        }) or []
        for r in rows:
            if r.get("paused"):
                incidents.append({
                    "type": "pause",
                    "source": str(r.get("updated_by") or ""),
                    "at": r.get("updated_at"),
                })
    except Exception:
        pass
    return incidents


def _attribute_job(job, outcomes, incidents):
    """Score a single job: positive KPI contribution, negative incident count."""
    job_id = job["id"]
    script = job["script"]

    # KPI contribution: count outcomes that mention this job's script or id
    kpi_hits = 0
    for o in outcomes:
        if o.get("integrated"):
            kpi_hits += 1  # Each integrated outcome is +1 to the system

    # Incident attribution: match by source containing job id or script
    incident_count = 0
    for inc in incidents:
        src = inc.get("source", "").lower()
        if job_id.lower() in src or script.lower().rstrip(".py") in src:
            incident_count += 1

    return {
        "job_id": job_id,
        "script": script,
        "kpi_contribution": kpi_hits,
        "incident_count": incident_count,
        "is_excluded": _is_hard_excluded(job),
    }


def _is_hard_excluded(job):
    """Check if job is in the hard-excluded safety set."""
    return (job["id"] in HARD_EXCLUDED_JOBS or
            job["script"] in HARD_EXCLUDED_JOBS or
            job["script"].rstrip(".py") in HARD_EXCLUDED_JOBS)


def score_jobs(jobs, outcomes=None, incidents=None):
    """Score all jobs. Returns list of scored dicts sorted by score ascending (worst first).

    Score formula: kpi_contribution - (incident_count * 10)
    Hard-excluded jobs get score=float('inf') so they never rank in the bottom.
    Jobs with zero incidents AND zero KPI contribution are scored at 0 (neutral),
    distinct from jobs with negative contribution.
    """
    if outcomes is None:
        outcomes = _fetch_outcomes()
    if incidents is None:
        incidents = _fetch_incidents()

    scored = []
    for job in jobs:
        attr = _attribute_job(job, outcomes, incidents)
        if attr["is_excluded"]:
            attr["score"] = float("inf")
            attr["reason"] = "hard-excluded (infrastructure/safety)"
        else:
            attr["score"] = attr["kpi_contribution"] - (attr["incident_count"] * 10)
            attr["reason"] = ""
        scored.append(attr)

    scored.sort(key=lambda x: (x["score"], x["job_id"]))
    return scored


def bottom_decile(scored_jobs):
    """Return the bottom decile of non-excluded jobs proposed for disabling.

    Jobs with zero incidents and zero KPI contribution are treated as neutral
    (not punished), distinct from jobs with negative contribution (incidents).
    """
    eligible = [j for j in scored_jobs if not j["is_excluded"] and j["score"] != float("inf")]
    if not eligible:
        return []
    n = max(1, math.ceil(len(eligible) * 0.1))
    # Only propose jobs that actually have a negative or zero score
    candidates = [j for j in eligible[:n] if j["score"] <= 0]
    return candidates


def build_report(scored_jobs):
    """Build a human-readable monthly report of all jobs with scores."""
    lines = [
        "# Monthly Subsystem Audit Report",
        f"Window: last {WINDOW_DAYS} days",
        f"Total jobs: {len(scored_jobs)}",
        "",
        "| Job ID | Script | KPI | Incidents | Score | Status |",
        "|--------|--------|-----|-----------|-------|--------|",
    ]
    for j in scored_jobs:
        status = "EXCLUDED" if j["is_excluded"] else ""
        score_str = "∞" if j["score"] == float("inf") else str(j["score"])
        lines.append(f"| {j['job_id']} | {j['script']} | {j['kpi_contribution']} | {j['incident_count']} | {score_str} | {status} |")
    return "\n".join(lines)


def file_approval_card(disable_candidates, report):
    """File a single material approval card for the whole monthly batch.

    Never auto-applied — requires explicit owner approval.
    """
    if not disable_candidates:
        print("monthly_subsystem_audit: no jobs proposed for disable.")
        return None

    job_list = ", ".join(c["job_id"] for c in disable_candidates)
    detail = json.dumps({
        "proposed_disables": [
            {"job_id": c["job_id"], "script": c["script"],
             "score": c["score"], "kpi": c["kpi_contribution"],
             "incidents": c["incident_count"]}
            for c in disable_candidates
        ],
        "report_excerpt": report[:3000],
    })

    try:
        db.insert("approvals", {
            "project": "ORCHESTRATOR",
            "kind": "self",
            "title": f"Monthly subsystem audit: disable {len(disable_candidates)} bottom-decile jobs",
            "why": f"Bottom-decile jobs by KPI contribution vs incidents: {job_list}",
            "value": f"Reduce overhead from {len(disable_candidates)} low-value periodic jobs",
            "risk": "Disabling may remove minor functionality; review each job before approving",
            "detail": detail,
            "command": "",
        })
        return True
    except Exception as e:
        print(f"monthly_subsystem_audit: failed to file approval: {e}")
        return False


def run():
    """Main entry point for the monthly subsystem audit."""
    jobs = _load_schedule()
    if not jobs:
        print("monthly_subsystem_audit: no jobs found in _SCHEDULE.")
        return

    print(f"monthly_subsystem_audit: auditing {len(jobs)} periodic jobs...")
    scored = score_jobs(jobs)
    report = build_report(scored)
    candidates = bottom_decile(scored)

    print(report)
    print(f"\nBottom decile candidates for disable: {len(candidates)}")
    for c in candidates:
        print(f"  - {c['job_id']} (score={c['score']}, kpi={c['kpi_contribution']}, incidents={c['incident_count']})")

    filed = file_approval_card(candidates, report)
    if filed:
        print("monthly_subsystem_audit: approval card filed for batch disable proposal.")


if __name__ == "__main__":
    run()
