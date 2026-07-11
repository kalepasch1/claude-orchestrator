#!/usr/bin/env python3
"""
repo_hygiene.py - shared filesystem hygiene checks for local repo checkouts, used by both
merge_train.py (before every test run) and queue_janitor.py (periodic sweep across all
registered projects).

STRAY COMPILED .js SHADOWING .ts: an ESM ("type":"module") project's runtime module
resolver can pick up a same-basename .js file over its .ts source, independent of git
tracking -- a leftover local tsc/build run that emitted output in-place instead of a
separate dist/ directory silently breaks every test/build that imports the shadowed
module. Observed twice on 2026-07-10: beethoven's web/ (10 files, tracked in git --
required an explicit git rm and a human decision) and tomorrow's server/ tree (4106
files, ALL untracked -- pure local build residue on one machine, invisible to git status
and therefore invisible to code review). This module only ever auto-removes UNTRACKED
files. A tracked .js/.ts collision is a real content decision -- it might be an
intentionally-committed compiled fallback -- so it is left alone and must be handled by a
human (as beethoven's was).

Fail-soft and fail-closed throughout: any error verifying safety (can't read package.json,
can't run git) results in doing nothing for that repo, never in deleting something we
couldn't verify.
"""
import json
import os
import subprocess

_SKIP_DIRS = {"node_modules", ".git", "dist", ".output", ".nuxt"}


def _is_esm_project(repo):
    try:
        with open(os.path.join(repo, "package.json")) as f:
            return json.load(f).get("type") == "module"
    except Exception:
        return False


def _tracked_files(repo):
    """Set of git-tracked paths (relative to repo root). None (fail closed -- caller must
    treat this as 'do nothing') if git itself can't be queried."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                             text=True, timeout=30)
        if out.returncode != 0:
            return None
        return set(out.stdout.splitlines())
    except Exception:
        return None


def find_stray_js_duplicates(repo):
    """Return relative paths of .js files that (1) have a same-basename .ts sibling in the
    same directory and (2) are NOT tracked by git. Only acts on ESM ("type":"module")
    projects -- that's the specific runtime resolution hazard this guards against."""
    if not _is_esm_project(repo):
        return []
    tracked = _tracked_files(repo)
    if tracked is None:
        return []
    strays = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        fileset = set(files)
        for fn in files:
            if not fn.endswith(".js"):
                continue
            if (fn[:-3] + ".ts") not in fileset:
                continue
            rel = os.path.relpath(os.path.join(root, fn), repo)
            if rel in tracked:
                continue
            strays.append(rel)
    return strays


def clean_stray_js_duplicates(repo):
    """Remove untracked stray .js files shadowing a .ts sibling. Returns the list of
    relative paths actually removed. Fail-soft: one removal failing doesn't stop the rest."""
    removed = []
    for rel in find_stray_js_duplicates(repo):
        try:
            os.remove(os.path.join(repo, rel))
            removed.append(rel)
        except OSError:
            continue
    return removed
