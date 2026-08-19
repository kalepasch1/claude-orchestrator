"""conflict_marker_sentinel — swarm remediation bot #1.

Detects files carrying unresolved git conflict markers and files a single, deduped,
tier-1 remediation task per location. Belt-and-suspenders to auto_conflict_resolver's
marker guard: that guard stops markers at the source; this catches any that survive it.

TWO locations, because they break the fleet in two different ways:

  scan(repo)           TRACKED files that carry markers ON HEAD. One such file breaks
                       every downstream compile / collection / canary gate — the
                       fleet-wide self-deploy stall.
  scan_worktree(repo)  TRACKED files that carry markers in the WORKING TREE, committed
                       or not. Strictly worse and completely invisible to a HEAD grep:
                       the pre-merge-commit anti-regression guard scans the working
                       tree, so ONE uncommitted marker file makes git refuse EVERY merge
                       commit into master on that node. Observed 2026-08-18 — three
                       uncommitted darwin-kernel files blocked every merge path while
                       HEAD itself was perfectly clean, so the HEAD-only sentinel saw
                       nothing while the whole node could not merge.

Pure + injectable: takes the repo path and an enqueue callable, so it is trivially
testable and INERT until wired. Wired into the periodic loop (~5 min) as:

    import conflict_marker_sentinel, enqueue
    conflict_marker_sentinel.sweep(REPO, enqueue.enqueue_task)
"""
import subprocess

MARKER = "^<<<<<<< "


def _git(args, repo):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def scan(repo):
    """Sorted list of tracked files on HEAD containing a conflict-start marker."""
    r = _git(["grep", "-l", "-e", MARKER, "HEAD"], repo)
    files = []
    for line in (r.stdout or "").splitlines():
        if ":" in line:
            files.append(line.split(":", 1)[1])
    return sorted(set(files))


def scan_worktree(repo):
    """Sorted list of tracked files whose WORKING-TREE content carries a marker.

    No rev argument, so `git grep` reads the files on disk rather than a commit — this
    is the only way to see markers that were never committed, and those are exactly the
    ones that make the pre-merge-commit guard refuse every merge.
    """
    r = _git(["grep", "-l", "-e", MARKER], repo)
    return sorted({ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()})


def _file_task(enqueue_fn, project_id, slug, files, prompt_head, prompt_tail):
    extra = (" (+%d more)" % (len(files) - 20)) if len(files) > 20 else ""
    rec = {
        "project_id": project_id,
        "slug": slug,
        "kind": "remediation",
        "priority": 1,  # tier-1: below user work (see ev_scheduler _self_improve_tier)
        "prompt": prompt_head + ", ".join(files[:20]) + extra + "." + prompt_tail,
        "note": "filed by conflict_marker_sentinel (swarm remediation bot #1)",
    }
    try:
        enqueue_fn(rec)
        return True
    except Exception:
        return False


_HEAD_PROMPT = ("Unresolved git conflict markers are committed on master in: ")
_HEAD_TAIL = (" Resolve them to the intended content so compile/collection/canary gates "
              "pass; these break self-deploy fleet-wide.")
_WT_PROMPT = ("Unresolved git conflict markers are sitting UNCOMMITTED in this node's "
              "working tree in: ")
_WT_TAIL = (" The pre-merge-commit anti-regression guard scans the working tree, so git "
            "is refusing EVERY merge commit into master on this node until they are "
            "cleared. Resolve each file to its intended content, or restore the committed "
            "version with `git checkout -- <file>` when HEAD is already correct. Back the "
            "discarded diff up first.")


def sweep(repo, enqueue_fn=None, project_id=None):
    """Detect markers on HEAD and in the working tree; file one deduped tier-1
    remediation task per location.

    Returns {'found': [...on HEAD...], 'worktree': [...worktree-only...], 'filed': bool}.
    'worktree' excludes anything already reported by 'found' so the two tasks do not
    describe the same file twice.
    """
    found = scan(repo)
    worktree = [p for p in scan_worktree(repo) if p not in set(found)]
    if not found and not worktree:
        return {"found": [], "worktree": [], "filed": False}
    filed = False
    if enqueue_fn is not None:
        if found:
            filed = _file_task(enqueue_fn, project_id,
                               "remediation-conflict-markers-on-master", found,
                               _HEAD_PROMPT, _HEAD_TAIL) or filed
        if worktree:
            filed = _file_task(enqueue_fn, project_id,
                               "remediation-conflict-markers-in-worktree", worktree,
                               _WT_PROMPT, _WT_TAIL) or filed
    return {"found": found, "worktree": worktree, "filed": filed}
