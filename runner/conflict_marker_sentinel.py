"""conflict_marker_sentinel — swarm remediation bot #1.

Detects TRACKED files that carry unresolved git conflict markers on HEAD and files a
single, deduped, tier-1 remediation task. Belt-and-suspenders to auto_conflict_resolver's
marker guard: that guard stops markers at the source; this catches any that still reach a
tracked commit via another merge path, because ONE such file breaks every downstream
compile / collection / canary gate — the fleet-wide self-deploy stall.

Pure + injectable: takes the repo path and an enqueue callable, so it is trivially testable
and INERT until wired. Wire it into the periodic loop (~5 min):

    import conflict_marker_sentinel, enqueue
    conflict_marker_sentinel.sweep(REPO, enqueue.enqueue_task)
"""
import subprocess

def _git(args, repo):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)

def scan(repo):
    """Sorted list of tracked files on HEAD containing a conflict-start marker."""
    r = _git(["grep", "-l", "-e", "^<<<<<<< ", "HEAD"], repo)
    files = []
    for line in (r.stdout or "").splitlines():
        if ":" in line:
            files.append(line.split(":", 1)[1])
    return sorted(set(files))

def sweep(repo, enqueue_fn=None, project_id=None):
    """Detect markers; on any, file one deduped tier-1 remediation task.
    Returns {'found': [...paths...], 'filed': bool}."""
    found = scan(repo)
    if not found:
        return {"found": [], "filed": False}
    filed = False
    if enqueue_fn is not None:
        extra = (" (+%d more)" % (len(found) - 20)) if len(found) > 20 else ""
        rec = {
            "project_id": project_id,
            "slug": "remediation-conflict-markers-on-master",
            "kind": "remediation",
            "priority": 1,  # tier-1: below user work (see ev_scheduler _self_improve_tier)
            "prompt": ("Unresolved git conflict markers are committed on master in: "
                       + ", ".join(found[:20]) + extra
                       + ". Resolve them to the intended content so compile/collection/"
                       "canary gates pass; these break self-deploy fleet-wide."),
            "note": "filed by conflict_marker_sentinel (swarm remediation bot #1)",
        }
        try:
            enqueue_fn(rec); filed = True
        except Exception:
            filed = False
    return {"found": found, "filed": filed}
