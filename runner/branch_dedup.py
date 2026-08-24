#!/usr/bin/env python3
"""
branch_dedup.py — detect duplicate and near-duplicate agent branches.

Identifies branches that point to the same commit (exact duplicates) or
share a common diff against base (semantic duplicates). Helps reduce
branch sprawl and wasted merge-train effort.

Env vars:
    ORCH_BRANCH_DEDUP_ENABLED   "true" to enable (default "true")
    ORCH_DEDUP_MAX_BRANCHES     max branches to scan (default 200)
"""
import os
import subprocess
import sys
import collections
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_BRANCH_DEDUP_ENABLED", "true").lower() in ("1", "true", "yes")
MAX_BRANCHES = int(os.environ.get("ORCH_DEDUP_MAX_BRANCHES", "200"))
TIMEOUT = 15


def _git(repo, *args):
    """Run a git command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=TIMEOUT)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _list_agent_branches(repo_path):
    """Return list of agent/ branch names."""
    rc, out, _ = _git(repo_path, "branch", "--list", "agent/*")
    if rc != 0 or not out:
        return []
    branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
    return branches[:MAX_BRANCHES]


def _branch_commit(repo_path, branch):
    """Return the HEAD commit hash of a branch."""
    rc, out, _ = _git(repo_path, "rev-parse", branch)
    return out if rc == 0 else None


def _diff_stat(repo_path, branch, base="master"):
    """Return the diffstat of branch vs base as a hashable string."""
    rc, out, _ = _git(repo_path, "diff", "--stat", f"{base}...{branch}")
    return out if rc == 0 else None


def find_exact_duplicates(repo_path):
    """Find branches pointing to the same commit.

    Returns list of {'commit': str, 'branches': [str], 'count': int}.
    """
    if not ENABLED or not repo_path or not os.path.isdir(repo_path):
        return []

    branches = _list_agent_branches(repo_path)
    commit_map = collections.defaultdict(list)
    for b in branches:
        commit = _branch_commit(repo_path, b)
        if commit:
            commit_map[commit].append(b)

    dupes = []
    for commit, names in commit_map.items():
        if len(names) > 1:
            dupes.append({"commit": commit[:12], "branches": sorted(names),
                          "count": len(names)})

    dupes.sort(key=lambda x: -x["count"])
    return dupes


def _diff_fingerprint(stat: str) -> str:
    """Stable fingerprint for a diffstat.

    Was `hash(stat) & 0xFFFFFFFF`. Python randomizes str hashing per process
    (PYTHONHASHSEED), so the same branches produced a DIFFERENT fingerprint on every
    run. Grouping still worked — it keys on the stat itself — but the number reported
    to the operator could not be compared between two reports, correlated with anything,
    or stored. A fingerprint that changes every run is worse than none, because it looks
    like one.
    """
    return hashlib.sha256((stat or "").encode("utf-8", "replace")).hexdigest()[:16]


def find_semantic_duplicates(repo_path, base="master"):
    """Find branches with identical diffs against base (same changes, different names).

    Returns list of {'diff_fingerprint': str, 'branches': [str], 'count': int,
    'empty_diff': bool}.
    """
    if not ENABLED or not repo_path or not os.path.isdir(repo_path):
        return []

    branches = _list_agent_branches(repo_path)
    stat_map = collections.defaultdict(list)
    for b in branches:
        stat = _diff_stat(repo_path, b, base)
        # `if stat:` here made the detector blind to its single largest category.
        #
        # A branch with NO diff against base — created, never committed to, or already
        # fully merged — returns "", which is falsey, so it was skipped. Those no-op
        # branches are the most duplicated thing in the repo: measured on this
        # checkout, 20 agent branches collapse onto 2 commits and the semantic pass
        # reported ZERO groups, because every one of them diffs empty against master.
        #
        # None means the diff could not be read (bad ref, timeout) and is still skipped;
        # "" is a real, and highly actionable, answer.
        if stat is None:
            continue
        stat_map[stat].append(b)

    dupes = []
    for stat, names in stat_map.items():
        if len(names) > 1:
            dupes.append({"diff_fingerprint": _diff_fingerprint(stat),
                          "branches": sorted(names), "count": len(names),
                          # Flagged rather than merely grouped: an empty-diff group is
                          # not "duplicate work to consolidate", it is "nothing to
                          # merge", and the two want opposite handling.
                          "empty_diff": stat == ""})

    dupes.sort(key=lambda x: (-x["count"], x["diff_fingerprint"]))
    return dupes


def dedup_report(repo_path, base="master"):
    """Generate a full deduplication report."""
    exact = find_exact_duplicates(repo_path)
    semantic = find_semantic_duplicates(repo_path, base)
    total_exact = sum(d["count"] for d in exact)
    total_semantic = sum(d["count"] for d in semantic)
    return {
        "exact_duplicate_groups": len(exact),
        "exact_duplicate_branches": total_exact,
        "semantic_duplicate_groups": len(semantic),
        "semantic_duplicate_branches": total_semantic,
        "exact": exact[:10],
        "semantic": semantic[:10],
    }


def run():
    """CLI entry point."""
    import json
    repo = os.environ.get("ORCH_REPO_PATH",
                          os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    report = dedup_report(repo)
    print(f"branch_dedup: {report['exact_duplicate_groups']} exact groups, "
          f"{report['semantic_duplicate_groups']} semantic groups")
    return report


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
