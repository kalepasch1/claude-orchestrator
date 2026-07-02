#!/usr/bin/env python3
"""
version.py - version the improvements themselves. v1 = the current full orchestration improvement queue.
A new version opens when a CRITICAL-MASS / novel improvement lands (e.g. a new Claude model, a new
capability class, a step-change in the platform) — not for routine merges. Each release_train release is
tagged with the current in-progress version; closing a version stamps a git tag + changelog.

CLI / API:
  status()         -> current version + release counts
  close(version, next_version, title)  -> mark version released, open the next
  tag_repos(version)                   -> create a git tag <version> in each repo at prod tip
"""
import os, sys, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def current():
    v = db.select("versions", {"select": "*", "status": "eq.in_progress",
                               "order": "opened_at.desc", "limit": "1"}) or []
    return v[0] if v else {"version": "v1"}


def status():
    cur = current()
    rel = db.select("releases", {"select": "id,project,deploy_status"}) or []
    ok = sum(1 for r in rel if r.get("deploy_status") == "success")
    return {"current_version": cur.get("version"), "title": cur.get("title"),
            "releases_total": len(rel), "releases_success": ok}


def tag_repos(version):
    tagged = 0
    for p in db.select("projects", {"select": "name,repo_path,prod_branch"}) or []:
        repo = p.get("repo_path", "")
        if not repo or not os.path.isdir(repo):
            continue
        prod = p.get("prod_branch") or "main"
        r = subprocess.run(["git", "tag", "-f", version, prod], cwd=repo, capture_output=True)
        if r.returncode == 0:
            if os.environ.get("ORCH_PUSH_ON_MERGE", "false").lower() == "true":
                subprocess.run(["git", "push", "-f", "origin", version], cwd=repo, capture_output=True)
            tagged += 1
    return tagged


def close(version, next_version, title, summary=""):
    """Mark a version released (tag repos), open the next."""
    tag_repos(version)
    db.update("versions", {"version": version},
              {"status": "released", "released_at": datetime.datetime.utcnow().isoformat()})
    db.insert("versions", {"version": next_version, "title": title, "summary": summary,
                           "status": "in_progress"}, upsert=True)
    print(f"version: closed {version}, opened {next_version} ({title})")
    return {"closed": version, "opened": next_version}


if __name__ == "__main__":
    import json
    if len(sys.argv) >= 4 and sys.argv[1] == "close":
        print(json.dumps(close(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]) or "next version")))
    else:
        print(json.dumps(status(), indent=2, default=str))
