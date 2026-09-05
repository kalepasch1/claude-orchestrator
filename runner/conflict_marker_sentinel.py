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
import os
import subprocess

MARKER = "^<<<<<<< "

#: An ORPHAN end-marker: a `=======` / `>>>>>>>` line whose opening `<<<<<<<` is gone.
#:
#: This is the artifact class the marker scans above cannot see, and it is the common
#: one. A half-resolved conflict is almost never abandoned mid-hunk — someone deletes
#: the `<<<<<<< HEAD` line and the side they do not want, saves, and misses the closing
#: `>>>>>>> branch` line at the bottom of the hunk. HEAD then contains a live merge
#: artifact while `scan()`, which greps only for the opening marker, reports the file
#: clean. "Ensure no merge artifacts remain" is not satisfied by an opening-marker grep.
ORPHAN_MARKER = "^(=======$|>>>>>>> )"

#: Files git itself leaves behind when a merge or `git apply` half-lands. `.orig` is the
#: pre-merge copy `merge.conflictStyle` writes; `.rej` is the hunk `git apply` could not
#: place. Both are untracked by default, so they survive `git status` habits and get
#: committed by an agent running `git add -A` — which is exactly how this executor
#: commits. A committed `.rej` is a merge artifact carrying a diff nobody applied.
LEFTOVER_SUFFIXES = (".orig", ".rej")


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


def scan_orphan_markers(repo):
    """Sorted tracked files carrying an end-marker with no matching opening marker.

    Files already reported by :func:`scan_worktree` are excluded — a whole, unresolved
    conflict is that function's finding, not a half-resolution. What is left is the
    genuinely invisible case: the opening marker was deleted, the closing one was not.
    """
    r = _git(["grep", "-lE", "-e", ORPHAN_MARKER], repo)
    hits = {ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()}
    return sorted(hits - set(scan_worktree(repo)))


def scan_leftover_files(repo):
    """Sorted tracked ``.orig`` / ``.rej`` paths — merge/apply debris that got committed.

    Only TRACKED paths count. An untracked ``.orig`` in someone's working copy is local
    mess; a tracked one is a merge artifact that shipped.
    """
    r = _git(["ls-files"], repo)
    return sorted(
        ln.strip()
        for ln in (r.stdout or "").splitlines()
        if ln.strip() and os.path.splitext(ln.strip())[1] in LEFTOVER_SUFFIXES
    )


def scan_artifacts(repo):
    """Every non-marker merge artifact: orphan end-markers plus committed debris."""
    return sorted(set(scan_orphan_markers(repo)) | set(scan_leftover_files(repo)))


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
_ART_PROMPT = ("Merge artifacts survived a resolution in: ")
_ART_TAIL = (" These carry no opening `<<<<<<<` marker, so the marker sentinel above "
             "reports the tree clean: either an orphan `=======`/`>>>>>>>` line whose "
             "opening marker was deleted during a half-resolution, or a tracked "
             "`.orig`/`.rej` file that `git add -A` committed. Delete the debris files "
             "and resolve each orphan hunk to its intended content.")


def sweep(repo, enqueue_fn=None, project_id=None):
    """Detect merge damage in three places; file one deduped tier-1 task per place.

    Returns ``{'found': [...on HEAD...], 'worktree': [...worktree-only...],
    'artifacts': [...orphan markers + committed .orig/.rej...], 'filed': bool}``.

    The lists are disjoint and reported in escalating order of invisibility, so no file
    is described by two tasks: 'worktree' excludes anything in 'found', and 'artifacts'
    excludes anything in either. 'artifacts' is the half-resolved case — no opening
    marker survives, so both marker scans call the tree clean while a live merge
    artifact sits on HEAD.
    """
    found = scan(repo)
    worktree = [p for p in scan_worktree(repo) if p not in set(found)]
    seen = set(found) | set(worktree)
    artifacts = [p for p in scan_artifacts(repo) if p not in seen]
    if not found and not worktree and not artifacts:
        return {"found": [], "worktree": [], "artifacts": [], "filed": False}
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
        if artifacts:
            filed = _file_task(enqueue_fn, project_id,
                               "remediation-merge-artifacts", artifacts,
                               _ART_PROMPT, _ART_TAIL) or filed
    return {"found": found, "worktree": worktree,
            "artifacts": artifacts, "filed": filed}
