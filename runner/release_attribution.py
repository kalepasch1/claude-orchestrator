#!/usr/bin/env python3
"""Exact task/outcome -> release attribution from Git commit evidence."""
import json
import os
import subprocess
import time


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__), "..", ".runtime"))


def _path():
    return os.path.join(_home(), "release-attribution.jsonl")


def _messages(repo, before, after):
    if not repo or not after:
        return ""
    range_spec = f"{before}..{after}" if before else after
    try:
        return subprocess.check_output(["git", "log", "--format=%H%n%B", range_spec],
                                       cwd=repo, text=True, stderr=subprocess.DEVNULL,
                                       timeout=30).lower()
    except Exception:
        return ""


def _commit_in_range(repo, commit, before, after):
    """Return true when commit is reachable from after but not from before."""
    if not repo or not commit or not after:
        return False
    try:
        inside = subprocess.run(["git", "merge-base", "--is-ancestor", commit, after], cwd=repo,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15).returncode == 0
        already = bool(before) and subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, before], cwd=repo,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15).returncode == 0
        return inside and not already
    except Exception:
        return False


def _existing_keys():
    try:
        with open(_path()) as f:
            return {(r.get("outcome_id"), r.get("release_id"))
                    for r in (json.loads(x) for x in f if x.strip())}
    except Exception:
        return set()


def attribute_release(project, repo, release, database=None):
    if database is None:
        import db as database
    messages = _messages(repo, release.get("from_sha"), release.get("to_sha"))
    manifest = None
    try:
        import release_manifest
        manifest = release_manifest.find_candidate(project, release.get("to_sha"))
    except Exception:
        manifest = None
    manifest_tasks = manifest.get("tasks", []) if manifest else []
    manifest_task_ids = {str(t.get("id")) for t in manifest_tasks if t.get("id")}
    manifest_slugs = {str(t.get("slug") or "").lower() for t in manifest_tasks if t.get("slug")}
    if not messages and not manifest_tasks:
        return {"attributed": 0, "reason": "no-release-commit-evidence"}
    outcome_query = {"select": "id,task_id,slug,model,project,integrated,created_at",
                     "project": f"eq.{project}", "order": "created_at.desc", "limit": "5000"}
    # An outcome cannot have caused a release that predates it.  Without this
    # upper bound a retried slug can inherit an older deployment, reversing the
    # measured winner between execution workflows.
    release_time = release.get("deployed_at") or release.get("created_at")
    if release_time:
        outcome_query["created_at"] = f"lte.{release_time}"
    outcomes = database.select("outcomes", outcome_query) or []
    unmatched_ids = [str(o.get("task_id")) for o in outcomes
                     if o.get("task_id") and str(o.get("slug") or "").lower() not in messages]
    tasks = {}
    if unmatched_ids:
        try:
            task_rows = []
            # Keep PostgREST URLs bounded; a 1,000-UUID `in` filter can exceed
            # proxy limits and silently erase all artifact attribution.
            for start in range(0, len(unmatched_ids), 50):
                batch = unmatched_ids[start:start + 50]
                task_rows.extend(database.select("tasks", {
                    "select": "id,slug,state,artifact_commit", "id": f"in.({','.join(batch)})",
                    "limit": "50"}) or [])
            tasks = {str(t.get("id")): t for t in task_rows}
        except Exception:
            tasks = {}
    keys = _existing_keys(); rows = []
    for outcome in outcomes:
        slug = str(outcome.get("slug") or "").lower()
        message_evidence = bool(slug and (slug in messages or f"agent/{slug}" in messages))
        manifest_evidence = (str(outcome.get("task_id")) in manifest_task_ids
                             or bool(slug and slug in manifest_slugs))
        task = tasks.get(str(outcome.get("task_id"))) or {}
        artifact_evidence = (str(task.get("state") or "").upper() == "MERGED"
                             and _commit_in_range(repo, task.get("artifact_commit"),
                                                  release.get("from_sha"), release.get("to_sha")))
        if not message_evidence and not artifact_evidence and not manifest_evidence:
            continue
        key = (outcome.get("id"), release.get("id"))
        if key in keys:
            continue
        if artifact_evidence and not outcome.get("integrated"):
            try:
                database.update("outcomes", {"id": outcome.get("id")}, {"integrated": True})
            except Exception:
                pass
        rows.append({"at": time.time(), "outcome_id": outcome.get("id"),
                     "task_id": outcome.get("task_id"), "slug": outcome.get("slug"),
                     "model": outcome.get("model"), "project": project,
                     "release_id": release.get("id"), "commit": release.get("to_sha"),
                     "evidence": ("immutable-release-manifest" if manifest_evidence else
                                  "git-release-range" if message_evidence else
                                  "task-artifact-release-range")})
    if rows:
        os.makedirs(os.path.dirname(_path()), exist_ok=True)
        with open(_path(), "a") as f:
            for row in rows:
                f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    return {"attributed": len(rows), "release_id": release.get("id")}


def apply(outcomes, authoritative=False):
    try:
        with open(_path()) as f:
            rows = [json.loads(x) for x in f if x.strip()]
    except Exception:
        rows = []
    ids = {r.get("outcome_id") for r in rows}
    by_slug = {(str(r.get("project") or "").lower(), str(r.get("slug") or "").lower()) for r in rows}
    result = []
    for original in outcomes or []:
        row = dict(original)
        key = (str(row.get("project") or "").lower(), str(row.get("slug") or "").lower())
        if row.get("id") in ids or key in by_slug:
            row["deployed"] = True
            row["deployment_evidence"] = "git-release-range"
        elif authoritative and row.get("deployment_evidence") == "project-release-window":
            row["deployed"] = False
            row.pop("deploy_status", None)
            row["deployment_evidence"] = "no-exact-release-link"
        result.append(row)
    return result


def backfill(limit=100):
    import db
    projects = {p.get("name"): p for p in (db.select("projects", {"select": "name,repo_path"}) or [])}
    releases = db.select("releases", {"select": "id,project,from_sha,to_sha,deploy_status,deployed_at",
                                       "deploy_status": "eq.success", "order": "created_at.desc",
                                       "limit": str(limit)}) or []
    total = 0
    for release in releases:
        p = projects.get(release.get("project")) or {}
        total += attribute_release(release.get("project"), p.get("repo_path"), release, db).get("attributed", 0)
    print(f"release_attribution: attributed={total} releases={len(releases)}")
    return {"attributed": total, "releases": len(releases)}


if __name__ == "__main__":
    print(json.dumps(backfill(), indent=2))
