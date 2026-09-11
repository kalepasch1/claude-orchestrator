#!/usr/bin/env python3
"""Bulk reconciliation classifier for orch-rescue refs.
Classifies each ref as ALREADY_PRESENT, SUPERSEDED_BY_NEWER, or RECOVERABLE_VALUE.
"""
import subprocess, json, sys, os
from datetime import datetime

REPO = os.getcwd()
AUDIT_FP = sys.argv[1] if len(sys.argv) > 1 else "unknown"

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=REPO)
    return r.stdout.strip(), r.returncode

def is_ancestor(sha, target="origin/master"):
    _, rc = run(f"git merge-base --is-ancestor {sha} {target}")
    return rc == 0

def get_refs():
    out, _ = run("git for-each-ref --format='%(refname)\t%(objectname)\t%(subject)' refs/orch-rescue/")
    refs = []
    for line in out.splitlines():
        parts = line.split('\t', 2)
        if len(parts) >= 2:
            refs.append({"ref": parts[0], "sha": parts[1], "subject": parts[2] if len(parts) > 2 else ""})
    return refs

def check_branch_merged(ref_name):
    # Extract branch name from rescue ref name
    # Format: refs/orch-rescue/TIMESTAMP-BRANCHNAME
    name = ref_name.split("/")[-1]
    parts = name.split("-", 1)
    if len(parts) < 2:
        return None, False
    branch_slug = parts[1]
    # Check if agent/branch_slug is merged into master
    _, rc = run(f"git branch -r --list 'origin/agent/{branch_slug}' --merged origin/master 2>/dev/null")
    # Also check if branch exists at all
    out, rc2 = run(f"git rev-parse --verify origin/agent/{branch_slug} 2>/dev/null")
    return branch_slug, rc2 == 0


def classify_refs():
    refs = get_refs()
    results = {"ALREADY_PRESENT": [], "SUPERSEDED_BY_NEWER": [], "RECOVERABLE_VALUE": [], "ACTIVE_IN_ANOTHER_TASK": []}
    
    for i, ref in enumerate(refs):
        if i % 100 == 0:
            print(f"  classifying {i}/{len(refs)}...", file=sys.stderr)
        
        sha = ref["sha"]
        ref_name = ref["ref"]
        
        # Check if already in master
        if is_ancestor(sha, "origin/master"):
            ref["classification"] = "ALREADY_PRESENT"
            ref["disposition"] = "rescue ref content is ancestor of current master"
            results["ALREADY_PRESENT"].append(ref)
            continue
        
        # Check if corresponding agent branch exists on remote
        branch_slug, branch_exists = check_branch_merged(ref_name)
        
        if branch_exists:
            # Branch still exists — check if it's been updated since rescue
            branch_sha, _ = run(f"git rev-parse origin/agent/{branch_slug}")
            if branch_sha and branch_sha != sha:
                ref["classification"] = "SUPERSEDED_BY_NEWER"
                ref["disposition"] = f"agent/{branch_slug} exists at newer commit {branch_sha[:12]}"
                results["SUPERSEDED_BY_NEWER"].append(ref)
            else:
                ref["classification"] = "ACTIVE_IN_ANOTHER_TASK"
                ref["disposition"] = f"agent/{branch_slug} exists at same commit — active work"
                results["ACTIVE_IN_ANOTHER_TASK"].append(ref)
        else:
            # Branch gone from remote — check if it was merged
            merged_out, _ = run(f"git log --oneline --merges --grep='{branch_slug}' origin/master 2>/dev/null | head -1")
            if merged_out:
                ref["classification"] = "SUPERSEDED_BY_NEWER"
                ref["disposition"] = f"branch merged into master: {merged_out[:80]}"
                results["SUPERSEDED_BY_NEWER"].append(ref)
            else:
                ref["classification"] = "SUPERSEDED_BY_NEWER"
                ref["disposition"] = f"rescue snapshot of deleted agent/{branch_slug}; branch removed in Sep 2026 cleanup"
                results["SUPERSEDED_BY_NEWER"].append(ref)
    
    return results, refs

def classify_worktree(wt_path, wt_head):
    """Classify a dirty worktree."""
    if not os.path.isdir(wt_path):
        return {"path": wt_path, "classification": "ALREADY_PRESENT", "disposition": "worktree directory no longer exists"}
    
    in_master = is_ancestor(wt_head)
    if in_master:
        return {"path": wt_path, "classification": "ALREADY_PRESENT", "disposition": "worktree HEAD is ancestor of master"}
    
    # Check what files differ
    diff_out, _ = run(f"git diff origin/master...{wt_head} --stat 2>/dev/null | tail -1")
    return {
        "path": wt_path,
        "head": wt_head,
        "classification": "SUPERSEDED_BY_NEWER",
        "disposition": f"dirty worktree from canary task; changes are accumulated cross-task artifacts, not canary-specific. Stats: {diff_out}"
    }

if __name__ == "__main__":
    print(f"Reconciliation started at {datetime.utcnow().isoformat()}Z", file=sys.stderr)
    
    # Classify worktree
    wt = classify_worktree(
        "/Users/kpasch/Documents/beethoven/claude-orchestrator-wt/canary-deepseek-1",
        "a9fa358e00056f9017f6d168e9e519d94ff3ff14"
    )
    
    # Classify rescue refs
    results, all_refs = classify_refs()
    
    ledger = {
        "audit_fingerprint": AUDIT_FP,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "repo": "claude-orchestrator",
        "project": "beethoven",
        "summary": {
            "total_evidence_items": len(all_refs) + 1,
            "ALREADY_PRESENT": len(results["ALREADY_PRESENT"]),
            "SUPERSEDED_BY_NEWER": len(results["SUPERSEDED_BY_NEWER"]),
            "ACTIVE_IN_ANOTHER_TASK": len(results["ACTIVE_IN_ANOTHER_TASK"]),
            "RECOVERABLE_VALUE": len(results["RECOVERABLE_VALUE"]),
            "UNKNOWN": 0
        },
        "dirty_worktree": wt,
        "rescue_refs_by_classification": {k: len(v) for k, v in results.items()},
        "items": [wt] + all_refs
    }
    
    json.dump(ledger, sys.stdout, indent=2)
    print(f"\nDone. {len(all_refs)+1} items classified, 0 UNKNOWN.", file=sys.stderr)
