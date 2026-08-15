#!/usr/bin/env python3
"""
Analyze merged branch patterns and write to memory.

Usage: python3 analyze_merged_branches.py [--num-branches 20] [--output-path memory_file.md]

Extracts: branch naming conventions, task types, diff statistics, file churn patterns,
test coverage discipline, merge velocity.
"""

import subprocess
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from typing import NamedTuple


class BranchStats(NamedTuple):
    """Stats for a single merged branch."""
    commit_hash: str
    branch_name: str
    files_changed: int
    insertions: int
    deletions: int
    commit_msg: str
    has_tests: bool = False


def run_git(cmd: str, cwd: Path | str = ".") -> str:
    """Run a git command and return output."""
    result = subprocess.run(
        f"cd {cwd} && {cmd}",
        shell=True,
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


def get_merged_commits(limit: int = 20, cwd: Path | str = ".") -> list[str]:
    """Get commit hashes of last N merged commits."""
    log_output = run_git(
        f"git log --oneline -n {limit} master",
        cwd=cwd
    )
    return [line.split()[0] for line in log_output.split("\n") if line]


def get_branch_name_from_commit(commit_hash: str, cwd: Path | str = ".") -> str:
    """Extract branch name from commit message (best effort)."""
    msg = run_git(f"git log -1 --format=%B {commit_hash}", cwd=cwd)
    # Look for patterns like 'agent/xxx', 'recover-xxx', etc.
    match = re.search(r'(agent/[\w\-]+|recover[\w\-]*|regen[\w\-]*)', msg)
    if match:
        return match.group(1)
    # Fallback: use commit message first line
    return msg.split("\n")[0][:60]


def get_diff_stats(commit_hash: str, cwd: Path | str = ".") -> tuple[int, int, int]:
    """Get files changed, insertions, deletions for a commit."""
    diff_output = run_git(
        f"git show --stat {commit_hash}",
        cwd=cwd
    )
    # Parse the summary line: "N files changed, X insertions(+), Y deletions(-)"
    files = 0
    insertions = 0
    deletions = 0

    lines = diff_output.split("\n")
    # Summary line is usually near the end
    for line in reversed(lines):
        if "files changed" in line:
            # Parse: "6 files changed, 994 insertions(+), 5 deletions(-)"
            files_match = re.search(r"(\d+)\s+files? changed", line)
            ins_match = re.search(r"(\d+)\s+insertions?", line)
            del_match = re.search(r"(\d+)\s+deletions?", line)

            if files_match:
                files = int(files_match.group(1))
            if ins_match:
                insertions = int(ins_match.group(1))
            if del_match:
                deletions = int(del_match.group(1))
            break

    return files, insertions, deletions


def get_commit_message(commit_hash: str, cwd: Path | str = ".") -> str:
    """Get first line of commit message."""
    msg = run_git(f"git log -1 --format=%B {commit_hash}", cwd=cwd)
    return msg.split("\n")[0] if msg else "Unknown"


def has_test_changes(commit_hash: str, cwd: Path | str = ".") -> bool:
    """Check if commit touches test files."""
    diff_output = run_git(f"git show --name-only {commit_hash}", cwd=cwd)
    # Look for common test patterns
    test_patterns = [
        r"test_", r"/test/", r"_test\.py", r"\.test\.", r"spec\.",
        r"tests/", r"__tests__"
    ]
    for line in diff_output.split("\n"):
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in test_patterns):
            return True
    return False


def analyze_branches(limit: int = 20, cwd: Path | str = ".") -> list[BranchStats]:
    """Analyze merged branches."""
    commits = get_merged_commits(limit, cwd)
    stats = []

    for commit_hash in commits:
        branch_name = get_branch_name_from_commit(commit_hash, cwd)
        files, ins, dels = get_diff_stats(commit_hash, cwd)
        msg = get_commit_message(commit_hash, cwd)
        has_tests = has_test_changes(commit_hash, cwd)

        stats.append(BranchStats(
            commit_hash=commit_hash,
            branch_name=branch_name,
            files_changed=files,
            insertions=ins,
            deletions=dels,
            commit_msg=msg,
            has_tests=has_tests
        ))

    return stats


def categorize_task_type(branch_name: str, msg: str) -> str:
    """Categorize branch by task type."""
    combined = f"{branch_name} {msg}".lower()

    if any(w in combined for w in ["qafix", "relfix", "deployfix", "fix("]):
        return "Fixes"
    elif any(w in combined for w in ["canary", "test", "ci/"]):
        return "Testing/Canary"
    elif any(w in combined for w in ["breach", "remediation", "recover"]):
        return "Recovery/Remediation"
    elif any(w in combined for w in ["rework", "improve", "refactor"]):
        return "Improvements/Refactoring"
    else:
        return "Other"


def generate_markdown(stats: list[BranchStats]) -> str:
    """Generate markdown analysis."""
    now = datetime.now().isoformat()

    # Aggregate stats
    total_files = sum(s.files_changed for s in stats)
    total_ins = sum(s.insertions for s in stats)
    total_dels = sum(s.deletions for s in stats)
    with_tests = sum(1 for s in stats if s.has_tests)

    # Categorize
    categories = Counter(
        categorize_task_type(s.branch_name, s.commit_msg)
        for s in stats
    )

    md = f"""---
name: merged-diff-patterns
description: "Last {len(stats)} merged branches categorized by task type with diff statistics, file change patterns, and test coverage analysis"
metadata:
  node_type: memory
  type: project
  updated: {datetime.now().strftime('%Y-%m-%d')}
  branches_analyzed: {len(stats)}
  date_analysis: {datetime.now().strftime('%Y-%m-%d')}
  modified: {now}
---

# Merged Branch Diff Analysis (Last {len(stats)} Commits)

**Analysis date:** {datetime.now().strftime('%Y-%m-%d')}
**Branches analyzed:** {len(stats)}
**Analysis method:** Automated via `runner/tools/analyze_merged_branches.py`

## Task-Type Distribution

| Category | Count | % |
|----------|-------|---|
"""

    for category, count in categories.most_common():
        pct = (count / len(stats)) * 100
        md += f"| {category} | {count} | {pct:.0f}% |\n"

    md += f"""
## Aggregate Statistics

| Metric | Value |
|--------|-------|
| Total branches analyzed | {len(stats)} |
| Total files touched | {total_files} |
| Avg files per branch | {total_files / len(stats):.1f} |
| Total insertions | {total_ins} |
| Total deletions | {total_dels} |
| Net change | +{total_ins - total_dels} lines |
| Branches with test changes | {with_tests} ({100*with_tests/len(stats):.0f}%) |

## Recent Merges (Full Detail)

"""

    for s in stats:
        test_marker = "✓ test" if s.has_tests else "  code"
        md += f"- **{s.commit_hash[:7]}** `{s.branch_name}` [{test_marker}]\n"
        md += f"  - Message: {s.commit_msg}\n"
        md += f"  - Files: {s.files_changed} | +{s.insertions} -{s.deletions}\n\n"

    md += f"""---

Related memories: [[git-merged-branches]], [[git-merged-branches-patterns]], [[merged-branch-analysis]]
"""

    return md


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-branches", type=int, default=20,
                        help="Number of commits to analyze (default 20)")
    parser.add_argument("--cwd", type=str, default=".",
                        help="Git repo working directory")
    parser.add_argument("--output-path", type=str, default=None,
                        help="Output file path (default: memory file)")
    args = parser.parse_args()

    # Analyze
    print(f"Analyzing last {args.num_branches} merged branches...")
    stats = analyze_branches(args.num_branches, args.cwd)

    # Generate markdown
    markdown = generate_markdown(stats)

    # Write to memory file if not specified
    if args.output_path:
        Path(args.output_path).write_text(markdown)
        print(f"Wrote analysis to {args.output_path}")
    else:
        # Default memory location
        memory_dir = Path.home() / ".claude" / "projects" / "-Users-kpasch-Documents-beethoven-claude-orchestrator" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        output_file = memory_dir / "merged_diff_patterns.md"
        output_file.write_text(markdown)
        print(f"Wrote analysis to {output_file}")

    # Print summary
    print(f"\nAnalyzed {len(stats)} branches:")
    for stat in stats[:5]:
        print(f"  {stat.commit_hash[:7]} {stat.branch_name:40s} +{stat.insertions:4d} -{stat.deletions:4d}")


if __name__ == "__main__":
    main()
