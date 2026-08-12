#!/usr/bin/env python3
"""Scoped re-audit: does every MERGED / DEPLOYED_AND_VERIFIED artifact_commit
exist in ITS OWN project's repo?

The two earlier attempts at this were both wrong in the same way: a single SHA
index built from a subset of repos, so commits belonging to unindexed repos were
reported "missing". This checks each sha ONLY against the repo of the project
that owns the task, and refuses to call anything missing in a repo it could not
probe."""
import json, os, subprocess, sys, urllib.request
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(REPO, "runner", ".env")
cfg = {}
for line in open(ENV, encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    cfg[k.strip()] = v.strip().strip('"').strip("'")

URL = cfg.get("SUPABASE_URL", "").rstrip("/")
KEY = cfg.get("SUPABASE_SERVICE_KEY") or cfg.get("SUPABASE_SERVICE_ROLE_KEY") or cfg.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("missing SUPABASE_URL / service key in runner/.env")


def rest(path):
    req = urllib.request.Request(
        f"{URL}/rest/v1/{path}",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


projects = {p["id"]: p for p in rest("projects?select=id,name,repo_path")}

rows, offset = [], 0
while True:
    page = rest(
        "tasks?select=slug,project_id,artifact_commit,state,account"
        "&state=in.(MERGED,DEPLOYED_AND_VERIFIED)"
        "&artifact_commit=not.is.null"
        f"&limit=1000&offset={offset}"
    )
    rows += page
    if len(page) < 1000:
        break
    offset += 1000

print(f"tasks with a commit in MERGED/DEPLOYED_AND_VERIFIED: {len(rows)}")

# ── probe health: a repo must resolve its own HEAD before we trust a miss ────
repo_ok = {}
for pid, p in projects.items():
    path = p.get("repo_path") or ""
    if not path or not os.path.isdir(os.path.join(path, ".git")):
        repo_ok[pid] = False
        continue
    head = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    if head.returncode != 0:
        repo_ok[pid] = False
        continue
    sane = subprocess.run(["git", "-C", path, "cat-file", "-e", head.stdout.strip() + "^{commit}"],
                          capture_output=True, text=True)
    repo_ok[pid] = sane.returncode == 0

cache = {}


def exists(pid, sha):
    key = (pid, sha)
    if key in cache:
        return cache[key]
    path = projects[pid]["repo_path"]
    r = subprocess.run(["git", "-C", path, "cat-file", "-e", f"{sha}^{{commit}}"],
                       capture_output=True, text=True)
    cache[key] = r.returncode == 0
    return cache[key]


stats = defaultdict(lambda: {"exist": 0, "missing": 0, "uncheckable": 0})
missing = defaultdict(list)
for t in rows:
    pid = t["project_id"]
    name = projects.get(pid, {}).get("name", f"<unknown {pid}>")
    sha = (t["artifact_commit"] or "").strip()
    if pid not in projects or not repo_ok.get(pid):
        stats[name]["uncheckable"] += 1
        continue
    if len(sha) < 7 or any(c not in "0123456789abcdefABCDEF" for c in sha):
        stats[name]["uncheckable"] += 1
        continue
    if exists(pid, sha):
        stats[name]["exist"] += 1
    else:
        stats[name]["missing"] += 1
        missing[name].append((sha, t["slug"], t.get("account") or "-"))

print("\nproject                          exist  missing  uncheckable  probe")
tot = {"exist": 0, "missing": 0, "uncheckable": 0}
for name in sorted(stats):
    s = stats[name]
    pid = next((k for k, v in projects.items() if v["name"] == name), None)
    probe = "ok" if repo_ok.get(pid) else "REPO UNREADABLE"
    print(f"{name:32s} {s['exist']:5d}  {s['missing']:7d}  {s['uncheckable']:11d}  {probe}")
    for k in tot:
        tot[k] += s[k]
print(f"{'TOTAL':32s} {tot['exist']:5d}  {tot['missing']:7d}  {tot['uncheckable']:11d}")

if missing:
    print("\nMISSING (sha claimed by a task whose own repo does not contain it):")
    for name in sorted(missing):
        print(f"  --- {name}")
        for sha, slug, acct in sorted(missing[name]):
            print(f"      {sha[:12]}  {slug[:70]:70s}  {acct}")

# ── the two commits the original P0 named, probed against EVERY repo ────────
print("\nthe two most-claimed commits from the original filing, probed in every repo:")
for sha in ("59de85f238e67d19deff89054ded7795f9b22a4a",
            "47f26779ebe654b491d211769c7456f074e187ad"):
    found = [projects[pid]["name"] for pid in projects
             if repo_ok.get(pid) and exists(pid, sha)]
    claims = sorted({t["slug"] for t in rows if (t["artifact_commit"] or "").strip() == sha})
    print(f"  {sha[:12]}  found_in={found or 'NONE'}  claimed_by={len(claims)} task(s)")
    for c in claims:
        print(f"      {c}")


# ==========================================================================
# PART 2 — is artifact_commit EVIDENCE? A commit claimed by many tasks points
# at an integration commit, not at each task's own change.
# ==========================================================================

byc = defaultdict(list)
for t in rows:
    byc[(t["project_id"], (t["artifact_commit"] or "").strip())].append(t)

buckets = defaultdict(int)
for k, v in byc.items():
    n = len(v)
    b = "1" if n == 1 else "2" if n == 2 else "3-5" if n <= 5 else "6-10" if n <= 10 else "11-30" if n <= 30 else "31+"
    buckets[b] += 1

print(f"distinct (project, commit) pairs: {len(byc)}   tasks: {len(rows)}")
print("\ntasks claiming the same commit — distribution over commits:")
for b in ("1", "2", "3-5", "6-10", "11-30", "31+"):
    print(f"  {b:>6s} task(s) per commit : {buckets[b]:5d} commit(s)")

shared = sum(len(v) for v in byc.values() if len(v) > 1)
print(f"\ntasks whose artifact_commit is shared with at least one other task: "
      f"{shared} of {len(rows)} ({100*shared/len(rows):.1f}%)")

print("\ntop 12 commits by number of claiming tasks:")
for (pid, sha), v in sorted(byc.items(), key=lambda kv: -len(kv[1]))[:12]:
    name = projects.get(pid, {}).get("name", "?")
    path = projects.get(pid, {}).get("repo_path", "")
    subj = ""
    files = ""
    if path and os.path.isdir(os.path.join(path, ".git")):
        r = subprocess.run(["git", "-C", path, "log", "-1", "--format=%s", sha],
                           capture_output=True, text=True)
        subj = r.stdout.strip()[:60] if r.returncode == 0 else "<not in repo>"
        rf = subprocess.run(["git", "-C", path, "show", "--stat", "--format=", sha],
                            capture_output=True, text=True)
        files = f"{len([l for l in rf.stdout.splitlines() if '|' in l])} file(s)" if rf.returncode == 0 else ""
    print(f"  {len(v):3d} tasks  {sha[:12]}  {name:14s}  {files:12s}  {subj}")

# every miss, examined properly: gone from the object store AND the reflog means
# the branch was discarded, not merely unreachable from a ref.
if missing:
    print("\ncommits absent from their own repo — deeper probe:")
    for name in sorted(missing):
        pid = next(k for k, v in projects.items() if v["name"] == name)
        path = projects[pid]["repo_path"]
        reflog = subprocess.run(["git", "-C", path, "reflog", "--all"],
                                capture_output=True, text=True).stdout
        for sha, slug, acct in sorted(missing[name]):
            t = subprocess.run(["git", "-C", path, "cat-file", "-t", sha],
                               capture_output=True, text=True).stdout.strip()
            print(f"  {name:10s} {sha:12s} in_reflog={sha in reflog}  "
                  f"object={t or 'absent'}  claimed_by={slug}  account={acct}")
