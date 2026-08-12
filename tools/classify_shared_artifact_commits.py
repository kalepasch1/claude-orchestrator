#!/usr/bin/env python3
"""P1 R4 backfill: classify every task whose artifact_commit is shared with
another task as justified or unattributed — and write an audit row per change.

READ-ONLY BY DEFAULT. `--apply` is deliberately not implemented as a bulk state
update: the filing names an unaudited bulk state change as itself a tracked
defect. This tool emits the audit rows; a state change may only be made from
them, one at a time, by a verifier.

    python3 tools/classify_shared_artifact_commits.py            # summary
    python3 tools/classify_shared_artifact_commits.py --json OUT # audit rows
    python3 tools/classify_shared_artifact_commits.py --all      # incl. sole claimants

Reuses tools/audit_merged_evidence.py's scoping discipline: each sha is probed
ONLY against the repo of the project that owns the task, and a repo whose HEAD
does not resolve makes its tasks uncheckable rather than missing.
"""
import argparse
import json
import os
import sys
import subprocess
import urllib.request
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "runner"))

import artifact_evidence as ev  # noqa: E402

STATES = "(MERGED,DEPLOYED_AND_VERIFIED)"


def _config():
    cfg = {}
    path = os.path.join(REPO, "runner", ".env")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return cfg


def _rest(cfg, path):
    url = cfg.get("SUPABASE_URL", "").rstrip("/")
    key = (cfg.get("SUPABASE_SERVICE_KEY") or cfg.get("SUPABASE_SERVICE_ROLE_KEY")
           or cfg.get("SUPABASE_KEY"))
    if not url or not key:
        raise SystemExit("missing SUPABASE_URL / service key in runner/.env")
    req = urllib.request.Request(
        "{0}/rest/v1/{1}".format(url, path),
        headers={"apikey": key, "Authorization": "Bearer " + key,
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _fetch_tasks(cfg):
    rows, offset = [], 0
    while True:
        page = _rest(cfg,
                     "tasks?select=id,slug,project_id,artifact_commit,artifact_branch,"
                     "state,account,prompt"
                     "&state=in." + STATES +
                     "&artifact_commit=not.is.null"
                     "&limit=1000&offset={0}".format(offset))
        rows += page
        if len(page) < 1000:
            break
        offset += 1000
    return rows


def _repo_probe_ok(path):
    if not path or not os.path.isdir(os.path.join(path, ".git")):
        return False
    head = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return head.returncode == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", dest="json_out", help="write audit rows to this path")
    ap.add_argument("--all", action="store_true",
                    help="classify every cited task, not just shared commits")
    ap.add_argument("--limit", type=int, default=0, help="stop after N tasks (debug)")
    args = ap.parse_args(argv)

    cfg = _config()
    projects = {p["id"]: p for p in _rest(cfg, "projects?select=id,name,repo_path")}
    tasks = _fetch_tasks(cfg)

    counts = defaultdict(int)
    for t in tasks:
        counts[(t["project_id"], (t.get("artifact_commit") or "").strip())] += 1

    probe_cache = {}
    rows, tally = [], defaultdict(int)
    for t in tasks:
        key = (t["project_id"], (t.get("artifact_commit") or "").strip())
        n = counts[key]
        if n <= 1 and not args.all:
            continue
        project = projects.get(t["project_id"], {})
        repo_path = project.get("repo_path") or ""
        if repo_path not in probe_cache:
            probe_cache[repo_path] = _repo_probe_ok(repo_path)
        if not probe_cache[repo_path]:
            tally["repo_unreadable"] += 1
            continue
        verdict = ev.classify_claim(t, repo_path, claim_count=n)
        verdict["project"] = project.get("name", "?")
        tally[verdict["verdict"]] += 1
        rows.append(ev.audit_row(verdict, actor_role="verifier",
                                 action="p1_backfill_classify",
                                 previous_state=t.get("state"), new_state=None))
        if args.limit and len(rows) >= args.limit:
            break

    total = sum(tally.values())
    print("classified {0} task(s) ({1} shared-commit population)".format(
        total, "all cited" if args.all else "shared-commit only"))
    for name in (ev.JUSTIFIED, ev.SOLE_CLAIMANT, ev.UNATTRIBUTED,
                 ev.UNRESOLVABLE, ev.NO_CITATION, "repo_unreadable"):
        if tally.get(name):
            print("  {0:16s} {1:5d}".format(name, tally[name]))
    print("\nrepo-less citations (R2 violations — bare sha, unverifiable by construction): "
          "{0}".format(sum(1 for r in rows if not r["repo_known"])))
    print("NO state was changed. Each row below is the audit record a verifier must "
          "write alongside any change it makes.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2)
        print("audit rows -> {0}".format(args.json_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
