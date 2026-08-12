#!/usr/bin/env python3
"""
blast_radius.py - before/while changing code, compute what a change could break by finding
the files that import/depend on the ones being touched, and tell the agent to add targeted
tests for that radius. Safer autonomous merges.

note_for_task(repo, prompt)  - heuristic: which modules the task targets + their dependents.
radius_after(repo, base)     - exact dependents of the files actually changed in the diff.

Both of the above see only THIS repo's import graph. The expensive failures on this fleet
are cross-app — a renamed table another app reads by name, a deleted endpoint another app
calls over HTTP — and those are not import edges, so nothing here can see them. When a
project name is supplied, shared_world_model supplies that half and it is folded into the
same answer.
"""
import os, sys, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_retrieval as cr

try:
    import shared_world_model as _swm
except Exception:      # fail-soft: the local radius must still work without the world model
    _swm = None

__all__ = ["note_for_task", "radius_after", "cross_app_radius_after"]


def _dependents(repo, files):
    deps = set()
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        if len(stem) < 3:
            continue
        try:
            r = subprocess.run(["rg", "-l", rf"(import|require|from).*{re.escape(stem)}"],
                               cwd=repo, capture_output=True, text=True, timeout=20)
            for d in r.stdout.splitlines():
                if d and d not in files:
                    deps.add(d)
        except Exception:
            pass
    return sorted(deps)


def _changed_files(repo, base="main"):
    try:
        return subprocess.check_output(["git", "diff", "--name-only", f"{base}...HEAD"],
                                       cwd=repo, text=True, timeout=30).split()
    except Exception:
        return []


def radius_after(repo, base="main", project=None):
    """Dependents of the files actually changed in the diff.

    `project` is optional and additive: when given, the cross-app radius from the shared
    world model is attached under "cross_app". Callers that ignore the new key keep the
    exact shape they had before.
    """
    changed = _changed_files(repo, base)
    out = {"changed": changed, "dependents": _dependents(repo, changed)}
    if project and _swm:
        try:
            out["cross_app"] = _swm.cross_app_radius(project, changed).get("impacted", [])
        except Exception:
            out["cross_app"] = []
    return out


def cross_app_radius_after(repo, project, base="main"):
    """Only the OTHER apps a merged diff would disturb. [] when unavailable."""
    if not _swm or not project:
        return []
    try:
        return _swm.cross_app_radius(project, _changed_files(repo, base)).get("impacted", [])
    except Exception:
        return []


def note_for_task(repo, prompt, project=None):
    """Prompt-injection block: in-repo dependents, plus cross-app surfaces when known.

    `project` is optional so every existing two-argument caller keeps working; without it
    the note is exactly what it was before.
    """
    targets = cr.select_files(repo, prompt)[:6]
    deps = _dependents(repo, targets)
    local = ""
    if deps:
        local = ("# Blast radius: these files depend on what you're likely changing - keep them "
                 "working and ADD/UPDATE tests covering them:\n" +
                 "\n".join(f"- {d}" for d in deps[:12]) + "\n\n")
    cross = ""
    if project and _swm:
        try:
            cross = _swm.note_for_task(project, prompt) or ""
        except Exception:
            cross = ""
    return local + cross


if __name__ == "__main__":
    print(radius_after(sys.argv[1] if len(sys.argv) > 1 else ".",
                       project=sys.argv[2] if len(sys.argv) > 2 else None))
