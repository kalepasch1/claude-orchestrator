#!/usr/bin/env python3
"""
Diagnostic tool for missing branch analysis.
This script analyzes the merge-train pressure state and identifies root causes of missing branches.

NEVER ANSWER "DOES BRANCH X EXIST?" FROM A LOCAL REF
----------------------------------------------------
`git branch -r` lists remote-TRACKING refs, which are a snapshot of the last
`git fetch`. In a clone that has not fetched recently they are simply stale, and
a branch that is present on origin reads as missing. A wrong "missing" here is
expensive rather than merely noisy: it files a reconstruct-the-patch task, and
the agent then rebuilds work that was on origin the whole time. This module's
entire task family — `backlog-batch-beethoven-ccacb00-verify-branch-existence-
reconstruct-minimal-patch` and its siblings — was generated exactly that way:
`agent/backlog-batch-beethoven-ccacb00` is on origin at 988649bb.

So branch existence is answered against ORIGIN, via
`branch_availability_check.branch_exists_remote()` (`git ls-remote --heads`),
which already existed and which this diagnostic simply was not calling. Every
verdict below reports the SOURCE it came from, so a later reader can re-verify
the claim instead of inheriting it.
"""
import os, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner"))
import db

try:
    import branch_availability_check as _bac
except Exception:  # pragma: no cover - diagnostic must run even if runner is unimportable
    _bac = None
    print("WARNING: branch_availability_check unavailable; "
          "remote branch verification degraded to local refs")


#: Verdicts. UNKNOWN is deliberately distinct from MISSING — "we could not ask
#: origin" must never be recorded as "it is not there", because that is the
#: reading that files a spurious reconstruct-the-patch task.
PRESENT = "PRESENT"
MISSING = "MISSING"
UNKNOWN = "UNKNOWN"


def branch_status(repo, branch):
    """Authoritative existence verdict for `branch`, answered from origin.

    Returns ``(verdict, source)`` where verdict is PRESENT / MISSING / UNKNOWN
    and source names where the answer came from, e.g. ``origin (ls-remote)``.
    Fail-soft: any error yields ``(UNKNOWN, ...)`` rather than raising or
    guessing MISSING.
    """
    if not repo or not isinstance(repo, str) or not os.path.isdir(repo):
        return UNKNOWN, "no usable repo path"
    if not branch or not isinstance(branch, str):
        return UNKNOWN, "no branch given"
    if _bac is not None:
        try:
            exists = _bac.branch_exists_remote(repo, branch)
            if exists is True:
                return PRESENT, "origin (ls-remote)"
            if exists is False:
                return MISSING, "origin (ls-remote)"
        except Exception:
            pass
    # Fallback: ask origin directly rather than falling back to a local ref.
    try:
        r = subprocess.run(["git", "ls-remote", "--heads", "origin", branch],
                           cwd=repo, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return (PRESENT if r.stdout.strip() else MISSING), "origin (ls-remote)"
    except Exception:
        pass
    return UNKNOWN, "origin unreachable — NOT treated as missing"


def write_branch_status(repo, branch, path="branch-status.txt"):
    """Write the verdict for `branch` to `path` and return it.

    The artifact this task family keeps asking to read and which nothing ever
    produced. Carries the source and the resolved SHA so the claim stays
    re-verifiable rather than becoming folklore.
    """
    verdict, source = branch_status(repo, branch)
    sha = ""
    if verdict == PRESENT:
        try:
            r = subprocess.run(["git", "ls-remote", "--heads", "origin", branch],
                               cwd=repo, capture_output=True, text=True, timeout=15)
            sha = (r.stdout.split() or [""])[0]
        except Exception:
            sha = ""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("%s\nbranch: %s\nsource: %s\nsha: %s\n"
                     % (verdict, branch, source, sha))
    except OSError as exc:  # pragma: no cover - fail-soft
        print("Could not write %s: %s" % (path, exc))
    return verdict

def analyze_missing_branches():
    """Analyze missing branch issues across projects."""
    
    # Get all projects
    projects = db.select("projects") or []
    project_map = {p["id"]: p for p in projects}
    
    print("=== Missing Branch Diagnostic Analysis ===")
    
    # Check merge-train pressure data
    try:
        pressure_rows = db.select("controls", {"select": "key,value", "key": "eq.merge_train_pressure"})
        if pressure_rows:
            pressure_data = json.loads(pressure_rows[0]["value"])
            print("\n--- Merge Train Pressure Data ---")
            for project_name, stats in pressure_data["projects"].items():
                print(f"Project: {project_name}")
                print(f"  Passed waiting: {stats['passed_waiting']}")
                print(f"  Missing branch: {stats['missing_branch']}")
                print(f"  Oldest wait age (s): {stats['oldest_wait_age_s']}")
                print(f"  Risk breakdown: low={stats['risk']['low']}, standard={stats['standard']}, sensitive={stats['sensitive']}")
    except Exception as e:
        print(f"Could not fetch pressure data: {e}")
    
    # Check for tasks with missing branches
    print("\n--- Tasks with Missing Branch Indicators ---")
    try:
        # Look for tasks that might be in a state indicating missing branches
        tasks = db.select("tasks", {
            "select": "id,slug,project_id,state,note",
            "order": "created_at.desc",
            "limit": 50
        }) or []
        
        missing_branch_tasks = []
        for task in tasks:
            note = task.get("note", "").lower()
            if any(keyword in note for keyword in ["missing", "branch", "rebuild", "redo"]):
                missing_branch_tasks.append(task)
        
        print(f"Found {len(missing_branch_tasks)} tasks with potential branch issues:")
        for task in missing_branch_tasks[:10]:  # Show first 10
            project_name = project_map.get(task["project_id"], {}).get("name", "unknown")
            print(f"  Task {task['id']}: {task['slug']} ({project_name}) - {task['note'][:100]}...")
            
    except Exception as e:
        print(f"Could not analyze tasks: {e}")
    
    # Check for approval cards with missing branches
    print("\n--- Approval Cards with Missing Branch Indicators ---")
    try:
        approvals = db.select("approvals", {
            "select": "id,slug,title,status,decided_by,kind",
            "order": "created_at.desc",
            "limit": 50
        }) or []
        
        missing_branch_approvals = []
        for approval in approvals:
            decided_by = approval.get("decided_by", "")
            if "missing" in decided_by.lower() or "no-repo" in decided_by.lower():
                missing_branch_approvals.append(approval)
        
        print(f"Found {len(missing_branch_approvals)} approval cards with missing branch indicators:")
        for approval in missing_branch_approvals[:10]:  # Show first 10
            print(f"  Card {approval['id']}: {approval['slug']} - {approval['decided_by']}")
            
    except Exception as e:
        print(f"Could not analyze approvals: {e}")

def check_branch_consistency():
    """Check consistency between database records and actual git branches."""
    print("\n=== Branch Consistency Check ===")
    
    # Get projects with repo paths
    projects = db.select("projects", {"select": "id,name,repo_path"}) or []
    
    for project in projects:
        project_id = project["id"]
        project_name = project["name"]
        repo_path = project["repo_path"]
        
        if not repo_path or not os.path.isdir(repo_path):
            print(f"Project {project_name}: Repo path missing or invalid")
            continue
            
        try:
            # ORIGIN, not `git branch -r`. Remote-tracking refs are a snapshot of the
            # last fetch; in a stale clone they under-report and every under-report
            # becomes a spurious reconstruct-the-patch task.
            result = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", "refs/heads/agent/*"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                # Could not ask origin. Say so; do NOT fall back to local refs and
                # do NOT report anything as missing.
                print(f"Project {project_name}: could not reach origin "
                      f"({(result.stderr or '').strip()[:120]}); "
                      f"branch existence UNKNOWN, nothing reported missing")
                continue

            on_origin = set()
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].startswith("refs/heads/"):
                    on_origin.add(parts[1][len("refs/heads/"):])

            print(f"Project {project_name}: {len(on_origin)} agent branches on origin")

            # Tasks whose work should be sitting on a branch right now.
            tasks = db.select("tasks", {
                "select": "id,slug,state",
                "project_id": f"eq.{project_id}",
                "state": "in.(DONE,MERGED,RUNNING)"
            }) or []

            truly_missing = [
                t for t in tasks
                if t.get("slug") and f"agent/{t['slug']}" not in on_origin
            ]
            print(f"  {len(tasks)} tasks expected to have a branch; "
                  f"{len(truly_missing)} with no branch ON ORIGIN")
            for task in truly_missing[:10]:
                # Re-verify individually before naming it — a wildcard listing that
                # was truncated or raced must not convict a branch on its own.
                verdict, source = branch_status(repo_path, f"agent/{task['slug']}")
                if verdict == MISSING:
                    print(f"    MISSING agent/{task['slug']} "
                          f"({task['state']}) [verified against {source}]")
                else:
                    print(f"    {verdict} agent/{task['slug']} "
                          f"({task['state']}) [{source}] — not missing after all")

        except Exception as e:
            print(f"Project {project_name}: Error checking branches - {e}")

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        # `diagnostic_missing_branch.py <branch> [repo]` — answer one branch and
        # write branch-status.txt, which is what the verify-branch-existence task
        # family asks to read.
        branch = argv[0]
        repo = argv[1] if len(argv) > 1 else os.path.dirname(os.path.abspath(__file__))
        verdict = write_branch_status(repo, branch)
        v, source = branch_status(repo, branch)
        print("%s %s [%s]" % (v, branch, source))
        # Exit 0 when present, 1 when genuinely missing, 2 when unanswerable.
        return {PRESENT: 0, MISSING: 1}.get(verdict, 2)
    analyze_missing_branches()
    check_branch_consistency()
    return 0


if __name__ == "__main__":
    sys.exit(main())
