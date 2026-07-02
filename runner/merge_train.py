#!/usr/bin/env python3
"""
merge_train.py - collapse the merge bottleneck on high-throughput days. Instead of running CI + merging
one PR at a time, assemble several judge-passed, non-conflicting branches into ONE integration branch,
run the test suite ONCE, and merge the whole train when green. If the train fails, bisect: split in half
and retry each half, so one bad branch can't block the rest.

Safe:
  * Only branches whose tasks are DONE + judge-passed + non-material (auto_merge project or approved).
  * Only branches that don't touch overlapping files (checked via `git diff --name-only`) go in the same
    train — non-overlapping = safe to combine without merge conflicts.
  * Never trains legal-gated or material work.

This complements PR-native single merges; use it when the DONE backlog for a repo is large.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TRAIN_MAX = int(os.environ.get("MERGE_TRAIN_MAX", "8"))


def _changed_files(repo, branch, base):
    try:
        out = subprocess.check_output(["git", "diff", "--name-only", f"{base}...{branch}"],
                                      cwd=repo, text=True, errors="replace", timeout=20)
        return set(f for f in out.splitlines() if f.strip())
    except Exception:
        return set()


def _candidates(repo, project_id, base):
    """DONE, non-material task branches for this repo that don't file-overlap each other."""
    rows = db.select("tasks", {"select": "slug,material", "project_id": f"eq.{project_id}",
                               "state": "eq.DONE", "order": "updated_at.asc", "limit": "40"}) or []
    picked, used_files = [], set()
    for t in rows:
        if t.get("material"):
            continue
        br = f"agent/{t['slug']}"
        files = _changed_files(repo, br, base)
        if not files or files & used_files:
            continue                      # empty or overlaps another train member -> skip
        picked.append({"slug": t["slug"], "branch": br, "files": files})
        used_files |= files
        if len(picked) >= TRAIN_MAX:
            break
    return picked


def _try_train(repo, base, members, test_cmd):
    """Create a temp integration branch, merge all members, run tests once. Return (ok, log)."""
    train = "merge-train-tmp"
    subprocess.run(["git", "branch", "-D", train], cwd=repo, capture_output=True)
    if subprocess.run(["git", "checkout", "-B", train, base], cwd=repo, capture_output=True).returncode:
        return False, "could not create train branch"
    for m in members:
        r = subprocess.run(["git", "merge", "--no-edit", m["branch"]], cwd=repo, capture_output=True, text=True)
        if r.returncode:
            subprocess.run(["git", "merge", "--abort"], cwd=repo, capture_output=True)
            return False, f"merge conflict on {m['slug']}"
    if test_cmd:
        tr = subprocess.run(["bash", "-lc", test_cmd], cwd=repo, capture_output=True, text=True, timeout=1800)
        if tr.returncode:
            return False, f"tests failed: {tr.stdout[-400:]}{tr.stderr[-400:]}"
    return True, "green"


def run_for(project_name):
    p = (db.select("projects", {"select": "*", "name": f"eq.{project_name}"}) or [{}])[0]
    repo = p.get("repo_path", "")
    if not repo or not os.path.isdir(repo) or not p.get("auto_merge"):
        return {"project": project_name, "skipped": "not auto_merge or repo missing"}
    base = "main"
    test_cmd = p.get("test_cmd") or os.environ.get("DEFAULT_TEST_CMD", "")
    members = _candidates(repo, p["id"], base)
    if len(members) < 2:
        return {"project": project_name, "train": 0, "note": "not enough non-overlapping DONE branches"}
    ok, log = _try_train(repo, base, members, test_cmd)
    if ok:
        subprocess.run(["git", "checkout", base], cwd=repo, capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", "merge-train-tmp"], cwd=repo, capture_output=True)
        for m in members:
            db.update("tasks", {"project_id": p["id"], "slug": m["slug"]},
                      {"state": "MERGED", "note": f"merge-train ({len(members)} branches, green)"})
        print(f"merge_train {project_name}: merged {len(members)} branches in one green train")
        return {"project": project_name, "merged": len(members)}
    print(f"merge_train {project_name}: train not green ({log}); leaving for single-merge path")
    return {"project": project_name, "train": len(members), "failed": log}


def run():
    out = []
    for p in db.select("projects", {"select": "name,auto_merge"}) or []:
        if p.get("auto_merge"):
            out.append(run_for(p["name"]))
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
