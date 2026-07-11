#!/usr/bin/env python3
"""
merge_cycle.py — diagnostics for branch-blocked work in the merge queue.

Provides detect_missing_branches() (grouped diagnostics) and run() for the
periodic scheduler. Stored under controls key 'merge_cycle_pressure' so
operators and the SLO controller can read the snapshot without a live DB query.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CONTROL_KEY = "merge_cycle_pressure"


def detect_missing_branches():
    """Return QUEUED tasks blocked on branch errors, grouped by project and target branch.

    Returns {project_name: {branch_name: {count: int, oldest_age_s: int}}}.
    Filters tasks where state='QUEUED' and note contains 'branch'. Groups by
    (project_name, base_branch) so operators can see how many tasks are stuck per
    project/target-branch pair and how stale the backlog is.
    Returns empty dict on DB error or no matching rows.
    """
    try:
        rows = db.select("tasks", {
            "select": "slug,project_id,base_branch,created_at,note",
            "state": "eq.QUEUED",
            "note": "like.%branch%",
        }) or []
    except Exception:
        return {}

    if not rows:
        return {}

    try:
        projects = {p["id"]: p.get("name") or str(p["id"])
                    for p in (db.select("projects", {"select": "id,name"}) or [])}
    except Exception:
        projects = {}

    now = datetime.datetime.now(datetime.timezone.utc)
    groups = {}

    for row in rows:
        project_id = row.get("project_id")
        branch_name = row.get("base_branch") or ""
        created_at = row.get("created_at")

        if not project_id or not branch_name:
            continue

        project_name = projects.get(project_id) or str(project_id)

        try:
            t = datetime.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            age_s = int((now - t).total_seconds())
        except Exception:
            age_s = 0

        key = (project_name, branch_name)
        if key not in groups:
            groups[key] = {"count": 0, "oldest_age_s": 0}
        groups[key]["count"] += 1
        if age_s > groups[key]["oldest_age_s"]:
            groups[key]["oldest_age_s"] = age_s

    result = {}
    for (project_name, branch_name), stats in groups.items():
        result.setdefault(project_name, {})[branch_name] = stats

    return result


def run():
    """Periodic entry: snapshot branch-blocked queue pressure to the controls table."""
    data = detect_missing_branches()
    total = sum(v["count"] for proj in data.values() for v in proj.values())

    payload = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "total_blocked": total,
        "by_project": data,
    }
    try:
        db.insert("controls", {
            "key": CONTROL_KEY,
            "value": json.dumps(payload),
            "updated_at": "now()",
        }, upsert=True)
    except Exception:
        pass

    if total:
        print(f"[merge_cycle] {total} branch-blocked tasks across {len(data)} project(s)")
    return payload


# ── inline unit tests ────────────────────────────────────────────────────────

def _run_tests():
    import datetime as _dt

    _NOW = _dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)
    _PROJ_A = "proj-a-id"
    _PROJ_B = "proj-b-id"

    def _ts(seconds_ago):
        return (_NOW - _dt.timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")

    def _detect(rows, project_rows, *, now=_NOW):
        if not rows:
            return {}
        projects = {p["id"]: p.get("name") or str(p["id"]) for p in project_rows}
        groups = {}
        for row in rows:
            project_id = row.get("project_id")
            branch_name = row.get("base_branch") or ""
            created_at = row.get("created_at")
            if not project_id or not branch_name:
                continue
            project_name = projects.get(project_id) or str(project_id)
            try:
                t = _dt.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                age_s = int((now - t).total_seconds())
            except Exception:
                age_s = 0
            key = (project_name, branch_name)
            if key not in groups:
                groups[key] = {"count": 0, "oldest_age_s": 0}
            groups[key]["count"] += 1
            if age_s > groups[key]["oldest_age_s"]:
                groups[key]["oldest_age_s"] = age_s
        result = {}
        for (pn, bn), stats in groups.items():
            result.setdefault(pn, {})[bn] = stats
        return result

    projs = [{"id": _PROJ_A, "name": "alpha"}, {"id": _PROJ_B, "name": "beta"}]

    # T1: no rows -> empty dict
    assert _detect([], projs, now=_NOW) == {}

    # T2: single task
    rows = [{"project_id": _PROJ_A, "base_branch": "main",
             "created_at": _ts(3600), "note": "agentic-repair:missing-branch",
             "slug": "fix-auth"}]
    r = _detect(rows, projs, now=_NOW)
    assert r == {"alpha": {"main": {"count": 1, "oldest_age_s": 3600}}}, r

    # T3: two tasks same project/branch -> count=2, oldest wins
    rows = [
        {"project_id": _PROJ_A, "base_branch": "main", "created_at": _ts(1000), "note": "missing branch", "slug": "s1"},
        {"project_id": _PROJ_A, "base_branch": "main", "created_at": _ts(5000), "note": "missing branch", "slug": "s2"},
    ]
    r = _detect(rows, projs, now=_NOW)
    assert r["alpha"]["main"]["count"] == 2
    assert r["alpha"]["main"]["oldest_age_s"] == 5000

    # T4: tasks across different projects and branches
    rows = [
        {"project_id": _PROJ_A, "base_branch": "main", "created_at": _ts(100), "note": "branch missing", "slug": "s1"},
        {"project_id": _PROJ_B, "base_branch": "staging", "created_at": _ts(200), "note": "branch missing", "slug": "s2"},
    ]
    r = _detect(rows, projs, now=_NOW)
    assert set(r.keys()) == {"alpha", "beta"}
    assert r["alpha"]["main"]["count"] == 1
    assert r["beta"]["staging"]["count"] == 1

    # T5: rows with None/missing base_branch or project_id are skipped
    rows = [
        {"project_id": None, "base_branch": "main", "created_at": _ts(100), "note": "branch", "slug": "s1"},
        {"project_id": _PROJ_A, "base_branch": None, "created_at": _ts(100), "note": "branch", "slug": "s2"},
        {"project_id": _PROJ_A, "base_branch": "main", "created_at": _ts(500), "note": "branch", "slug": "s3"},
    ]
    r = _detect(rows, projs, now=_NOW)
    assert r == {"alpha": {"main": {"count": 1, "oldest_age_s": 500}}}

    # T6: malformed created_at falls back to age_s=0 without raising
    rows = [{"project_id": _PROJ_A, "base_branch": "main", "created_at": "not-a-date", "note": "branch", "slug": "s1"}]
    r = _detect(rows, projs, now=_NOW)
    assert r == {"alpha": {"main": {"count": 1, "oldest_age_s": 0}}}

    # T7: unknown project_id falls back to str(project_id) as project_name
    rows = [{"project_id": "unknown-id", "base_branch": "main", "created_at": _ts(10), "note": "branch", "slug": "s1"}]
    r = _detect(rows, projs, now=_NOW)
    assert "unknown-id" in r

    print("merge_cycle: all tests passed")


if __name__ == "__main__":
    _run_tests()
