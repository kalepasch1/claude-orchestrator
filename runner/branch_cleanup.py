#!/usr/bin/env python3
"""
branch_cleanup.py — Automated cleanup of stale agent branches.

Identifies and removes agent/* branches that are:
- Already merged (state=MERGED in DB)
- Older than MAX_AGE_DAYS with no recent activity
- Orphaned (no matching task in DB)

Safety: never touches protected branches, always dry-run by default.
"""
import os, sys, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_AGE_DAYS = int(os.environ.get("ORCH_BRANCH_MAX_AGE_DAYS", "14"))
PROTECTED = {"main", "master", "dev", "staging", "production", "orchestrator/dev"}


def list_agent_branches(repo_path):
    """List all agent/* branches with their last commit date."""
    try:
        r = subprocess.run(
            ["git", "for-each-ref", "--sort=-committerdate",
             "--format=%(refname:short) %(committerdate:unix)", "refs/heads/agent/"],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return []
        branches = []
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.strip().split(" ", 1)
            name = parts[0]
            ts = int(parts[1]) if len(parts) > 1 else 0
            branches.append({"name": name, "last_commit_ts": ts})
        return branches
    except Exception:
        return []


def classify_branches(repo_path, project_id=None):
    """Classify branches as merged, stale, orphaned, or active."""
    branches = list_agent_branches(repo_path)
    now = time.time()
    max_age_s = MAX_AGE_DAYS * 86400

    # Get task slugs from DB
    try:
        tasks = db.select("tasks", {
            "select": "slug,state",
            **({"project_id": f"eq.{project_id}"} if project_id else {}),
        }) or []
        task_map = {t["slug"]: t["state"] for t in tasks}
    except Exception:
        task_map = {}

    result = {"merged": [], "stale": [], "orphaned": [], "active": []}

    for b in branches:
        slug = b["name"].replace("agent/", "", 1)
        state = task_map.get(slug)
        age = now - b["last_commit_ts"] if b["last_commit_ts"] else float("inf")

        if state == "MERGED":
            result["merged"].append(b["name"])
        elif state is None and age > max_age_s:
            result["orphaned"].append(b["name"])
        elif age > max_age_s:
            result["stale"].append(b["name"])
        else:
            result["active"].append(b["name"])

    return result


def cleanup(repo_path, project_id=None, dry_run=True):
    """Remove stale/merged/orphaned branches. Returns summary."""
    classified = classify_branches(repo_path, project_id)
    to_remove = classified["merged"] + classified["stale"] + classified["orphaned"]

    removed = []
    for branch in to_remove:
        if branch in PROTECTED:
            continue
        if dry_run:
            removed.append(f"[dry-run] {branch}")
        else:
            try:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    cwd=repo_path, capture_output=True, timeout=10,
                )
                removed.append(branch)
            except Exception:
                pass

    return {
        "removed": removed,
        "kept_active": len(classified["active"]),
        "dry_run": dry_run,
    }
