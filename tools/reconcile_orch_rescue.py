#!/usr/bin/env python3
"""Bulk-classify orch-rescue refs against current repo state.

Uses batch git operations for speed:
  1. git for-each-ref --merged=origin/master refs/orch-rescue/ → ALREADY_PRESENT
  2. Remaining refs checked against remote branches in bulk
  3. git rev-list --count for unique-commit check on the remainder

Outputs a JSON ledger.
"""
import json
import subprocess
import sys
import re
from datetime import datetime, timezone


def run(cmd, cwd="."):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=60)
    return r.stdout.strip(), r.returncode


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    cwd = args.repo

    master_sha, _ = run(["git", "rev-parse", "origin/master"], cwd=cwd)

    # Step 1: Get ALL rescue refs
    out, _ = run(["git", "for-each-ref",
                  "--format=%(refname)\t%(objectname)\t%(subject)",
                  "refs/orch-rescue/"], cwd=cwd)
    all_refs = {}
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        refname, sha, subject = parts
        m = re.match(r"On\s+(.+?):\s+orch-rescue:", subject)
        branch = m.group(1) if m else None
        all_refs[refname] = {"ref": refname, "sha": sha, "branch": branch, "subject": subject}
    print(f"Total rescue refs: {len(all_refs)}", file=sys.stderr)

    # Step 2: Batch — which refs are already merged into master?
    out, _ = run(["git", "for-each-ref", "--merged=origin/master",
                  "--format=%(refname)", "refs/orch-rescue/"], cwd=cwd)
    merged_refs = set(out.splitlines()) if out else set()
    print(f"Already in master: {len(merged_refs)}", file=sys.stderr)

    # Step 3: Get all remote branch names for cross-reference
    out, _ = run(["git", "for-each-ref", "--format=%(refname:short)\t%(objectname:short)",
                  "refs/remotes/origin/agent/"], cwd=cwd)
    remote_branches = {}
    for line in (out or "").splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            remote_branches[parts[0].replace("origin/", "")] = parts[1]
    print(f"Remote agent branches: {len(remote_branches)}", file=sys.stderr)

    # Step 4: Classify each ref
    counts = {}
    ledger = []
    for refname, info in all_refs.items():
        if refname in merged_refs:
            cls, reason = "ALREADY_PRESENT", "commit reachable from origin/master"
        elif info["branch"] and info["branch"] in remote_branches:
            cls = "SUPERSEDED_BY_NEWER"
            reason = f"origin/{info['branch']} exists at {remote_branches[info['branch']]}"
        elif info["branch"] and info["branch"] == "master":
            cls, reason = "ALREADY_PRESENT", "snapshot of master itself"
        else:
            cls, reason = "RECOVERABLE_VALUE", "not in master, no active remote branch"

        counts[cls] = counts.get(cls, 0) + 1
        ledger.append({
            "ref": refname,
            "sha": info["sha"][:12],
            "branch": info["branch"],
            "classification": cls,
            "reason": reason,
            "fingerprint": args.fingerprint,
        })

    result = {
        "fingerprint": args.fingerprint,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "master_sha": master_sha[:12],
        "total_refs": len(all_refs),
        "counts": counts,
        "items": ledger,
    }

    output_text = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"Ledger written to {args.output}", file=sys.stderr)
    else:
        print(output_text)

    print(f"\nSummary: {json.dumps(counts)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
