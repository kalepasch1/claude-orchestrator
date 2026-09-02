#!/usr/bin/env python3
"""Classify refs/orch-rescue/* against the default branch. Read-only: never
writes, moves, resets or deletes a ref. Emits JSON on stdout."""
import json, subprocess, sys, re

REPO = sys.argv[1]
BASE = sys.argv[2]          # e.g. origin/master
NS   = sys.argv[3]          # e.g. refs/orch-rescue/

def git(*a):
    p = subprocess.run(("git", "-C", REPO) + a, capture_output=True, text=True)
    return None if p.returncode != 0 else p.stdout

base_sha = git("rev-parse", BASE).strip()

remote_branches = set()
for line in (git("for-each-ref", "refs/remotes/origin/", "--format=%(refname:short)") or "").splitlines():
    remote_branches.add(line.replace("origin/", "", 1))

refs = []
for line in (git("for-each-ref", NS,
                 "--format=%(refname)|%(objectname)|%(creatordate:unix)|%(subject)") or "").splitlines():
    p = line.split("|", 3)
    if len(p) == 4:
        refs.append(dict(ref=p[0], sha=p[1], created_at=int(p[2]), subject=p[3]))

BRANCH_RE = re.compile(r"^On (?:branch )?([^:]+):")

def branch_of(subject):
    m = BRANCH_RE.match(subject)
    if not m:
        return None
    b = m.group(1).strip()
    return None if b in ("(no branch)", "no branch") else b

# One `git ls-tree -r` per revision, cached, instead of one `git rev-parse rev:path`
# per (revision, path) pair — the latter is thousands of subprocess spawns.
tree_cache = {}
def tree(rev):
    if rev not in tree_cache:
        m = {}
        for line in (git("ls-tree", "-r", "--format=%(objectname) %(path)", rev) or "").splitlines():
            sha, _, path = line.partition(" ")
            if path:
                m[path] = sha
        tree_cache[rev] = m
    return tree_cache[rev]

def blob(rev, path):
    return tree(rev).get(path)

# Newest commit date on BASE touching each path.
#
# This was one `git log -1 --format=%ct BASE -- <path>` per path. On a repo this
# size that is a full history walk per path, and with thousands of distinct paths
# across 384 refs the classifier ran for minutes without emitting a line. One
# `--name-only` pass over the same history costs under a second and answers every
# path at once.
touch_cache = {}
def _build_touch_map():
    ts = 0
    for line in (git("log", "--format=%ct", "--name-only", base_sha) or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.isdigit() and len(line) == 10:
            ts = int(line)
        elif ts and line not in touch_cache:
            touch_cache[line] = ts      # log is newest-first, so first write wins
_build_touch_map()

def base_last_touch(path):
    return touch_cache.get(path, 0)

items = []
for r in refs:
    mb = git("merge-base", r["sha"], base_sha)
    mb = mb.strip() if mb else None
    if not mb:
        items.append(dict(r, classification="CONFLICTED_NEEDS_FOCUSED_TASK", file_count=0, files=[],
                          evidence="no merge-base with %s; unrelated history" % BASE,
                          disposition="queue a focused task to inspect the orphaned ref by hand"))
        continue
    names = git("diff", "--name-only", mb, r["sha"])
    files = [f for f in (names or "").splitlines() if f]
    if not files:
        items.append(dict(r, classification="ALREADY_PRESENT", file_count=0, files=[],
                          evidence="no net diff against merge-base %s" % mb[:8],
                          disposition="nothing to recover"))
        continue

    # Content check: is every touched blob already byte-identical on BASE?
    identical, differing = [], []
    for f in files:
        (identical if blob(r["sha"], f) == blob(base_sha, f) else differing).append(f)
    if not differing:
        items.append(dict(r, classification="ALREADY_PRESENT", file_count=len(files), files=files[:25],
                          evidence="all %d touched path(s) byte-identical on %s" % (len(files), BASE),
                          disposition="content already landed; nothing to recover"))
        continue

    br = branch_of(r["subject"])
    if br and br in remote_branches:
        items.append(dict(r, classification="ACTIVE_IN_ANOTHER_TASK", file_count=len(files),
                          files=differing[:25], branch_hint=br,
                          evidence="rescue ref was cut on '%s', which still exists on origin" % br,
                          disposition="leave to the branch already carrying it; do not duplicate"))
        continue

    # Did BASE rewrite every differing path AFTER the ref was cut?
    newer = [f for f in differing if base_last_touch(f) > r["created_at"]]
    if len(newer) == len(differing):
        items.append(dict(r, classification="SUPERSEDED_BY_NEWER", file_count=len(files),
                          files=differing[:25],
                          evidence="all %d differing path(s) rewritten on %s after the ref was cut" % (len(differing), BASE),
                          disposition="newest wins; do not recover"))
        continue

    absent = [f for f in differing if blob(base_sha, f) is None]
    if absent and not newer:
        items.append(dict(r, classification="RECOVERABLE_VALUE", file_count=len(files),
                          files=differing[:25], absent_paths=absent[:25],
                          evidence="%d path(s) absent from %s and untouched since the ref was cut" % (len(absent), BASE),
                          disposition="queue a focused recovery task"))
        continue

    items.append(dict(r, classification="CONFLICTED_NEEDS_FOCUSED_TASK", file_count=len(files),
                      files=differing[:25],
                      evidence="%d of %d differing path(s) moved on %s after the ref was cut; partial overlap"
                               % (len(newer), len(differing), BASE),
                      disposition="queue a focused follow-up rather than forcing an overwrite"))

counts = {}
for i in items:
    counts[i["classification"]] = counts.get(i["classification"], 0) + 1
print(json.dumps(dict(base=BASE, base_sha=base_sha, namespace=NS,
                      total=len(items), counts=counts, items=items), indent=1))
