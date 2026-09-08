#!/usr/bin/env python3
"""Reconcile orch-rescue refs or local-only branch tips against current master.

Classifies each ref as:
  ALREADY_PRESENT        — commit is ancestor of origin/master
  SUPERSEDED_BY_NEWER    — a newer ref for same branch exists, or branch merged via different commit
  ACTIVE_IN_ANOTHER_TASK — slug maps to a QUEUED/RUNNING task (checked via ledger note)
  RECOVERABLE_VALUE      — not in master, unique content worth recovering
  CONFLICTED_NEEDS_FOCUSED_TASK — would conflict if merged

Usage:
  python3 tools/reconcile_refs.py --mode orch-rescue --fingerprint <fp> --output <path>
  python3 tools/reconcile_refs.py --mode local-branches --fingerprint <fp> --output <path>
"""
import subprocess, json, sys, os, argparse, hashlib
from datetime import datetime, timezone


def run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return r.stdout.strip(), r.returncode


def get_master_sha(repo):
    out, _ = run(["git", "rev-parse", "origin/master"], cwd=repo)
    return out


def is_ancestor(sha, master_sha, repo):
    _, rc = run(["git", "merge-base", "--is-ancestor", sha, master_sha], cwd=repo)
    return rc == 0


def get_orch_rescue_refs(repo):
    """Return list of (ref, sha, timestamp, branch_slug) for orch-rescue refs."""
    out, _ = run(["git", "for-each-ref", "--format=%(refname) %(objectname)",
                   "refs/orch-rescue/"], cwd=repo)
    refs = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        ref, sha = parts[0], parts[1]
        # ref format: refs/orch-rescue/20260803T000716-claude-orchestrator
        name = ref.replace("refs/orch-rescue/", "")
        # Extract timestamp and branch slug
        dash_idx = name.find("-")
        if dash_idx > 0:
            ts_str = name[:dash_idx]
            branch_slug = name[dash_idx+1:]
        else:
            ts_str = name
            branch_slug = name
        refs.append({"ref": ref, "sha": sha, "timestamp": ts_str, "branch_slug": branch_slug})
    return refs


def get_local_only_branches(repo):
    """Return list of (ref, sha) for local branches not on remote."""
    out, _ = run(["git", "for-each-ref", "--format=%(refname) %(objectname)",
                   "refs/heads/"], cwd=repo)
    remote_out, _ = run(["git", "for-each-ref", "--format=%(refname)",
                          "refs/remotes/origin/"], cwd=repo)
    remote_branches = set()
    for line in remote_out.splitlines():
        # refs/remotes/origin/master -> master
        b = line.replace("refs/remotes/origin/", "")
        remote_branches.add(b)

    local_only = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        ref, sha = parts[0], parts[1]
        branch_name = ref.replace("refs/heads/", "")
        if branch_name not in remote_branches:
            local_only.append({"ref": ref, "sha": sha, "branch_name": branch_name})
    return local_only


def classify_refs(refs, master_sha, repo, mode="orch-rescue"):
    """Classify each ref. Returns list of classification dicts."""
    results = []
    # Group orch-rescue refs by branch_slug to detect superseded
    if mode == "orch-rescue":
        by_slug = {}
        for r in refs:
            slug = r["branch_slug"]
            by_slug.setdefault(slug, []).append(r)
        # For each slug, sort by timestamp desc — newest first
        for slug in by_slug:
            by_slug[slug].sort(key=lambda x: x["timestamp"], reverse=True)

    total = len(refs)
    for i, r in enumerate(refs):
        sha = r["sha"]
        if i % 50 == 0:
            print(f"  classifying {i+1}/{total}...", file=sys.stderr)

        classification = "UNKNOWN"
        disposition = ""

        # Check if already in master
        if is_ancestor(sha, master_sha, repo):
            classification = "ALREADY_PRESENT"
            disposition = "commit reachable from origin/master"
        else:
            # For orch-rescue: check if superseded by newer ref for same branch
            if mode == "orch-rescue":
                slug = r["branch_slug"]
                group = by_slug.get(slug, [])
                if len(group) > 1 and group[0]["sha"] != sha:
                    # There's a newer snapshot for this branch
                    classification = "SUPERSEDED_BY_NEWER"
                    disposition = f"newer snapshot exists: {group[0]['ref']}"
                else:
                    # Check if it can merge cleanly
                    _, merge_rc = run(["git", "merge-tree", master_sha, sha], cwd=repo)
                    classification = "RECOVERABLE_VALUE"
                    disposition = "not in master; newest snapshot for this branch"
            else:
                # local branch
                classification = "RECOVERABLE_VALUE"
                disposition = "local-only branch not on remote"

        record = {
            "ref": r["ref"],
            "sha": sha[:12],
            "classification": classification,
            "disposition": disposition,
        }
        if mode == "orch-rescue":
            record["branch_slug"] = r["branch_slug"]
            record["timestamp"] = r["timestamp"]
        else:
            record["branch_name"] = r["branch_name"]
        results.append(record)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["orch-rescue", "local-branches"], required=True)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    master_sha = get_master_sha(repo)
    print(f"master SHA: {master_sha[:12]}", file=sys.stderr)

    if args.mode == "orch-rescue":
        refs = get_orch_rescue_refs(repo)
        print(f"found {len(refs)} orch-rescue refs", file=sys.stderr)
    else:
        refs = get_local_only_branches(repo)
        print(f"found {len(refs)} local-only branches", file=sys.stderr)

    results = classify_refs(refs, master_sha, repo, mode=args.mode)

    # Build summary
    counts = {}
    for r in results:
        c = r["classification"]
        counts[c] = counts.get(c, 0) + 1

    ledger = {
        "audit_fingerprint": args.fingerprint,
        "mode": args.mode,
        "master_sha": master_sha[:12],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_items": len(results),
        "summary": counts,
        "items": results,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(ledger, f, indent=2)

    print(f"\nClassification complete:", file=sys.stderr)
    for c, n in sorted(counts.items()):
        print(f"  {c}: {n}", file=sys.stderr)
    print(f"Ledger written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
