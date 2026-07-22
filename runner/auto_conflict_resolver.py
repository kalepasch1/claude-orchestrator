#!/usr/bin/env python3
"""
auto_conflict_resolver.py — intelligent merge-conflict resolution for agent branches.

The merge_train rebases branches serially, but when a branch conflicts, it marks
CONFLICT and moves on. This module adds a second pass: for branches with
ONLY config/shared-file conflicts, it can auto-resolve them.

Resolution strategies by file type:

  1. OURS_ALWAYS — files that are agent-local noise (.aider.*, .orch-context-cache.json,
     .deploy-canary, .ssw-bot-log.md). Use base version, discard branch version.

  2. THEIRS_ALWAYS — files where the branch version is definitionally correct
     (test files the branch added, new feature modules). Use branch version.

  3. REGENERATE — files that are derived artifacts. After merge, re-run the
     generator (prisma generate, npm install).

  4. UNION — files where both sides added content and the union is valid
     (e.g., .gitignore entries, migration files). Merge with --union strategy.

  5. MANUAL — files that need semantic understanding. Queue for human review.

Usage:
    python3 auto_conflict_resolver.py [--dry-run] [repo_path ...]

Environment:
    ORCH_AUTO_RESOLVE_ENABLED    Kill switch (default: true)
    ORCH_AUTO_RESOLVE_MAX_FILES  Max conflict files to auto-resolve per branch (default: 5)
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import db
except Exception:
    db = None

GIT_TIMEOUT = int(os.environ.get("WORKTREE_GC_GIT_TIMEOUT", "90"))
MAX_CONFLICT_FILES = int(os.environ.get("ORCH_AUTO_RESOLVE_MAX_FILES", "5"))

# ── Resolution strategy mapping ─────────────────────────────────────────────

# Files where we always keep the base (main/master) version
OURS_ALWAYS_PATTERNS = {
    ".aider.chat.history.md",
    ".aider.input.history",
    ".aider.tags.cache.v3",
    ".orch-context-cache.json",
    ".deploy-canary",
    ".ssw-bot-log.md",
    ".claude/settings.json",
}
OURS_ALWAYS_SUFFIXES = (".aider.", ".cache.", ".log.md")
OURS_ALWAYS_PREFIXES = (".aider",)
# Files where we take the branch version if it's an addition
THEIRS_IF_ADDED_PATTERNS = re.compile(
    r"(tests?/|__tests__/|\.test\.|\.spec\.|supabase/migrations/)"
)

# Files that should be regenerated after merge
REGENERATE_TRIGGERS = {
    "prisma/schema.prisma": "npx prisma generate",
    "package.json": "npm install --package-lock-only",
}

# Files where union merge works
UNION_PATTERNS = {".gitignore", ".eslintignore", ".prettierignore"}


def _git(args, repo, timeout=GIT_TIMEOUT):
    try:
        return subprocess.run(
            args, cwd=repo, capture_output=True, text=True,
            timeout=timeout, errors="replace"
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))

def _classify_conflict(filepath: str, conflict_type: str = "") -> str:
    """Classify a conflicting file into a resolution strategy."""
    normalized = filepath.strip()

    # Check OURS_ALWAYS
    if normalized in OURS_ALWAYS_PATTERNS:
        return "ours"
    for suffix in OURS_ALWAYS_SUFFIXES:
        if suffix in normalized:
            return "ours"
    for prefix in OURS_ALWAYS_PREFIXES:
        if os.path.basename(normalized).startswith(prefix):
            return "ours"

    # Check UNION
    if normalized in UNION_PATTERNS:
        return "union"

    # Check REGENERATE
    if normalized in REGENERATE_TRIGGERS:
        return "regenerate"

    # Check THEIRS_IF_ADDED (new test/migration files)
    if THEIRS_IF_ADDED_PATTERNS.search(normalized) and "add/add" in conflict_type.lower():
        return "theirs"

    # For add/add conflicts on new files, prefer the branch version
    if "add/add" in conflict_type.lower():
        return "theirs"

    # AST MERGER: try semantic merge for supported file types before giving up
    try:
        import ast_merger
        if ast_merger.can_handle(normalized):
            return "ast_merge"
    except Exception:
        pass

    return "manual"

def _resolve_file(repo: str, filepath: str, strategy: str, branch: str, base: str) -> bool:
    """Apply a resolution strategy to a single conflicting file."""
    if strategy == "ours":
        r = _git(["git", "checkout", "--ours", filepath], repo)
        if r.returncode == 0:
            _git(["git", "add", filepath], repo)
            return True
        return False
    elif strategy == "theirs":
        r = _git(["git", "checkout", "--theirs", filepath], repo)
        if r.returncode == 0:
            _git(["git", "add", filepath], repo)
            return True
        return False
    elif strategy == "union":
        r = _git(["git", "merge-file", "--union", filepath, filepath, filepath], repo)
        _git(["git", "add", filepath], repo)
        return True
    elif strategy == "regenerate":
        r = _git(["git", "checkout", "--ours", filepath], repo)
        if r.returncode == 0:
            _git(["git", "add", filepath], repo)
            return True
        return False
    elif strategy == "ast_merge":
        try:
            import ast_merger
            mb = _git(["git", "merge-base", base, branch], repo)
            merge_base = mb.stdout.strip() if mb.returncode == 0 else base
            result = ast_merger.try_semantic_merge(repo, filepath, merge_base, base, branch)
            if result["success"] and result["merged_content"]:
                fullpath = os.path.join(repo, filepath)
                with open(fullpath, "w") as f:
                    f.write(result["merged_content"])
                _git(["git", "add", filepath], repo)
                return True
        except Exception:
            pass
        return False
    return False

def resolve_branch(repo: str, branch: str, base: str, *, dry_run: bool = False) -> dict:
    """Try to merge a branch with auto-resolution of conflicts."""
    result = {
        "branch": branch, "merged": False, "strategy": "skipped",
        "resolved_files": [], "manual_files": [], "error": None,
    }

    # Step 1: attempt normal merge
    merge_result = _git(["git", "merge", "--no-ff", branch, "-m",
                         f"Merge branch '{branch}' (auto-resolved)"], repo)

    if merge_result.returncode == 0:
        if dry_run:
            _git(["git", "reset", "--hard", "HEAD~1"], repo)
        else:
            _git(["git", "branch", "-d", branch], repo)
        result["merged"] = True
        result["strategy"] = "clean"
        return result

    # Step 2: parse conflict files
    output = (merge_result.stderr or "") + "\n" + (merge_result.stdout or "")
    conflict_files = []
    for line in output.splitlines():
        if "Merge conflict in " in line:
            filepath = line.split("Merge conflict in ")[-1].strip()
            conflict_type = ""
            for prev_line in output.splitlines():
                if filepath in prev_line and "CONFLICT" in prev_line:
                    conflict_type = prev_line
                    break
            conflict_files.append((filepath, conflict_type))
    if not conflict_files:
        _git(["git", "merge", "--abort"], repo)
        result["error"] = "no parseable conflict files"
        return result

    # Step 3: classify each conflict
    strategies = {}
    for filepath, conflict_type in conflict_files:
        strategies[filepath] = _classify_conflict(filepath, conflict_type)

    manual_files = [f for f, s in strategies.items() if s == "manual"]
    auto_files = [(f, s) for f, s in strategies.items() if s != "manual"]

    if manual_files:
        _git(["git", "merge", "--abort"], repo)
        result["strategy"] = "manual"
        result["manual_files"] = manual_files
        result["resolved_files"] = [f for f, _ in auto_files]
        return result

    if len(conflict_files) > MAX_CONFLICT_FILES:
        _git(["git", "merge", "--abort"], repo)
        result["error"] = f"too many conflicts ({len(conflict_files)} > {MAX_CONFLICT_FILES})"
        return result

    if dry_run:
        _git(["git", "merge", "--abort"], repo)
        result["merged"] = True
        result["strategy"] = "auto"
        result["resolved_files"] = [f for f, _ in auto_files]
        return result
    # Step 4: resolve each file
    for filepath, strategy in auto_files:
        ok = _resolve_file(repo, filepath, strategy, branch, base)
        if ok:
            result["resolved_files"].append(filepath)
        else:
            _git(["git", "merge", "--abort"], repo)
            result["error"] = f"failed to resolve {filepath} with strategy {strategy}"
            return result

    # Step 5: commit the resolved merge
    commit = _git(["git", "commit", "--no-edit"], repo)
    if commit.returncode == 0:
        result["merged"] = True
        result["strategy"] = "auto"
        _git(["git", "branch", "-d", branch], repo)
    else:
        _git(["git", "merge", "--abort"], repo)
        _git(["git", "reset", "--hard", "HEAD"], repo)
        result["error"] = f"commit failed: {commit.stderr[:200]}"

    return result

def resolve_repo(repo: str, base: str, *, dry_run: bool = False) -> dict:
    """Run auto-conflict-resolution across all agent branches in a repo.
    Iterates in passes until no more merges succeed."""
    _git(["git", "checkout", base], repo)
    _git(["git", "reset", "--hard", "HEAD"], repo)
    _git(["git", "config", "user.name", "kalepasch1"], repo)
    _git(["git", "config", "user.email", "kalepasch@gmail.com"], repo)

    summary = {
        "repo": repo, "base": base, "passes": 0,
        "total_merged": 0, "auto_resolved": 0,
        "manual_remaining": 0, "skipped": 0, "details": [],
    }

    prev_merged = -1
    while summary["total_merged"] != prev_merged:
        prev_merged = summary["total_merged"]
        summary["passes"] += 1

        branches = _git(["git", "branch"], repo).stdout
        agent_branches = [
            b.strip().lstrip("* ") for b in branches.splitlines()
            if "agent/" in b
        ]

        for branch in sorted(agent_branches):
            r = resolve_branch(repo, branch, base, dry_run=dry_run)
            if r["merged"]:
                summary["total_merged"] += 1
                if r["strategy"] == "auto":
                    summary["auto_resolved"] += 1
            elif r["manual_files"]:
                summary["manual_remaining"] += 1
            else:
                summary["skipped"] += 1
            summary["details"].append(r)

        # Safety: max 10 passes to prevent infinite loops
        if summary["passes"] >= 10:
            break

    return summary


def run(dry_run: bool = False) -> dict:
    """Main entry point: resolve conflicts across all known repos.

    Reads project list from the DB, runs resolve_repo on each.
    Returns aggregate summary.
    """
    results = {"repos": [], "total_merged": 0, "auto_resolved": 0, "errors": []}

    if not db:
        # No DB — check if repos were passed as arguments
        return results

    try:
        projects = db.select("projects", {}) or []
    except Exception as e:
        results["errors"].append(f"db query failed: {e}")
        return results

    for proj in projects:
        repo = proj.get("repo_path", "")
        base = proj.get("base_branch") or proj.get("default_base") or "main"

        if not repo or not os.path.isdir(repo):
            continue

        try:
            r = resolve_repo(repo, base, dry_run=dry_run)
            results["repos"].append(r)
            results["total_merged"] += r.get("total_merged", 0)
            results["auto_resolved"] += r.get("auto_resolved", 0)
        except Exception as e:
            results["errors"].append(f"{repo}: {e}")

    return results


# ── Standalone mode ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json

    dry = "--dry-run" in sys.argv
    repos = [a for a in sys.argv[1:] if not a.startswith("--")]

    if repos:
        # Run on specific repos
        for repo_path in repos:
            base = "main"
            print(f"\n=== {repo_path} (base={base}) ===")
            r = resolve_repo(repo_path, base, dry_run=dry)
            print(_json.dumps({k: v for k, v in r.items() if k != "details"}, indent=2))
            if r.get("details"):
                merged = [d for d in r["details"] if d.get("merged")]
                manual = [d for d in r["details"] if d.get("manual_files")]
                print(f"  Merged: {len(merged)}, Manual: {len(manual)}")
    else:
        # Run across all DB projects
        print("auto_conflict_resolver: running across all projects...")
        result = run(dry_run=dry)
        print(_json.dumps({k: v for k, v in result.items() if k != "repos"}, indent=2))
        for repo_result in result.get("repos", []):
            print(f"  {repo_result['repo']}: merged={repo_result['total_merged']}, "
                  f"auto={repo_result['auto_resolved']}, "
                  f"manual={repo_result['manual_remaining']}")