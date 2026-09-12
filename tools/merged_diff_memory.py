#!/usr/bin/env python3
"""Merged-diff-to-memory bridge: extract diffs from recently-merged agent branches and store in project memory.

Scans git history for merge commits matching 'agent/*' branch patterns, extracts their diffs,
and writes structured memory files to ~/.claude/projects/<project>/memory/ for operator context.

Idempotent by commit hash: re-running never duplicates entries for the same merge commit.
No secrets/credentials are extracted (validates against common patterns before writing).
"""
from __future__ import annotations
import os
import re
import sys
import json
import hashlib
import datetime
import subprocess
from pathlib import Path
from typing import Optional

AGENT_BRANCH_PATTERN = re.compile(r"^agent/")
MERGE_COMMIT_PATTERN = re.compile(r"^Merge branch ['\"]agent/([^'\"]+)['\"]")
#: Patterns that are conclusive on their own. A PEM armour line IS the secret —
#: it carries no ':' or '=' and never will, so gating it on "looks like
#: key=value" (as the shared heuristic below does) let private keys through
#: unredacted into the auto-memory file.
CONCLUSIVE_SECRET_PATTERNS = [
    re.compile(r"-----(?:BEGIN|END)[ A-Z]*(?:PRIVATE KEY|CERTIFICATE|RSA|"
               r"OPENSSH|PGP|DSA|EC|ENCRYPTED)", re.IGNORECASE),
]

#: Keyword patterns. A line mentioning "token" is only interesting when it also
#: assigns something — otherwise every sentence about tokens redacts itself.
KEYWORD_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|credential|aws_|private_key|oauth)", re.IGNORECASE),
    re.compile(r"(algorithm|credential):", re.IGNORECASE),
]

#: Everything that marks a line as redactable, for callers that do not care which
#: kind matched (e.g. _sanitize_diff, which redacts on any hit).
SECRET_PATTERNS = CONCLUSIVE_SECRET_PATTERNS + KEYWORD_SECRET_PATTERNS


def _line_has_secret(line: str) -> bool:
    """True when this one line should be treated as carrying a secret."""
    if any(pat.search(line) for pat in CONCLUSIVE_SECRET_PATTERNS):
        return True
    if any(pat.search(line) for pat in KEYWORD_SECRET_PATTERNS):
        # A value has to actually be assigned for a keyword hit to mean anything.
        return ":" in line or "=" in line
    return False


def _has_secrets(text: str) -> bool:
    """Check if text contains likely secrets/credentials."""
    if not text:
        return False
    return any(_line_has_secret(line) for line in str(text)[:10000].split("\n"))


def _sanitize_diff(diff_text: str, max_chars: int = 50000) -> str:
    """Truncate diff and remove any lines matching secret patterns."""
    if not diff_text:
        return ""
    truncated = diff_text[:max_chars]
    lines = []
    for line in truncated.split("\n"):
        # Skip lines that look like they contain secrets
        if any(pat.search(line) for pat in SECRET_PATTERNS):
            lines.append(line[:30] + " [redacted]" if len(line) > 30 else "[redacted]")
        else:
            lines.append(line)
    return "\n".join(lines)


def get_recent_merged_agent_branches(repo: str, limit: int = 50) -> list[dict]:
    """Find recent merge commits of agent/* branches.

    Returns a list of dicts with keys: commit_hash, branch_name, merge_message, author_date.
    """
    try:
        # Get merge commits matching "Merge branch 'agent/*'"
        output = subprocess.check_output(
            [
                "git", "log",
                "--all", "--oneline", "--merges",
                f"--max-count={limit}",
                "--format=%H%n%s%n%aI%n---END---"
            ],
            cwd=repo,
            text=True,
            errors="replace",
            timeout=30,
        )
    except Exception:
        return []

    results = []
    entries = output.split("---END---")
    for entry in entries:
        lines = [l.strip() for l in entry.strip().split("\n") if l.strip()]
        if len(lines) < 3:
            continue
        commit_hash, message, author_date = lines[0], lines[1], lines[2]

        # Extract branch name from merge message
        m = MERGE_COMMIT_PATTERN.match(message)
        if not m:
            continue
        branch_name = m.group(1)

        results.append({
            "commit_hash": commit_hash,
            "branch_name": branch_name,
            "merge_message": message,
            "author_date": author_date,
        })
    return results


def get_merge_diff(repo: str, merge_commit: str, max_chars: int = 60000) -> str:
    """Extract the diff introduced by a merge commit (2-dot notation: parent1..merge)."""
    try:
        # Get diff from merge commit's first parent to the merge commit itself
        output = subprocess.check_output(
            ["git", "diff", f"{merge_commit}^..{merge_commit}"],
            cwd=repo,
            text=True,
            errors="replace",
            timeout=60,
        )
        return output[:max_chars]
    except Exception:
        return ""


def get_changed_files(repo: str, merge_commit: str) -> list[str]:
    """Get list of files changed in a merge commit."""
    try:
        output = subprocess.check_output(
            ["git", "diff", "--name-only", f"{merge_commit}^..{merge_commit}"],
            cwd=repo,
            text=True,
            errors="replace",
            timeout=30,
        )
        return [f for f in output.split("\n") if f.strip()]
    except Exception:
        return []


#: Directories that hold projects rather than being one. The project is the
#: segment that follows the LAST of these on the path.
_WORKSPACE_ANCHORS = ("Documents", "beethoven")


def _normalize_project_path(repo: str) -> str:
    """Extract the project identifier from a repo path.

    /Users/kpasch/Documents/beethoven/claude-orchestrator       -> claude-orchestrator
    /Users/kpasch/Documents/beethoven/claude-orchestrator/runner -> claude-orchestrator
    /Users/kpasch/Documents/apparently                          -> apparently
    /tmp/repo                                                   -> orchestrator

    This value keys the memory file (see write_memory_file), so returning the
    wrong segment does not just mislabel — it merges unrelated repos into one
    memory. Returning on the FIRST anchor did exactly that: every project under
    ~/Documents/beethoven/ resolved to "beethoven" and shared one file, so
    patterns learned from one repo were served as precedent for another.
    """
    parts = Path(repo).parts
    project = None
    for i, part in enumerate(parts):
        if part in _WORKSPACE_ANCHORS and i + 1 < len(parts):
            project = parts[i + 1]
    return project or "orchestrator"


def extract_merged_diffs(repo: str, limit: int = 50) -> list[dict]:
    """Extract metadata and diffs from recent merged agent branches.

    Returns list of dicts with keys: commit_hash, branch_name, merge_message, diff, files, author_date.
    Diffs with secrets are redacted; entries are deduplicated by commit hash.
    """
    branches = get_recent_merged_agent_branches(repo, limit=limit)
    results = []
    seen_hashes = set()

    for branch_info in branches:
        commit_hash = branch_info["commit_hash"]
        if commit_hash in seen_hashes:
            continue
        seen_hashes.add(commit_hash)

        diff = get_merge_diff(repo, commit_hash)
        if _has_secrets(diff):
            diff = _sanitize_diff(diff)

        files = get_changed_files(repo, commit_hash)

        results.append({
            "commit_hash": commit_hash,
            "branch_name": branch_info["branch_name"],
            "merge_message": branch_info["merge_message"],
            "diff": diff,
            "files": files,
            "author_date": branch_info["author_date"],
            "extracted_at": datetime.datetime.utcnow().isoformat(),
        })
    return results


def write_memory_file(project: str, merged_diffs: list[dict]) -> Optional[str]:
    """Write merged diffs to ~/.claude/projects/<project>/memory/merged_changes.md.

    Returns path to written file, or None on failure.
    Idempotent: only appends new commit hashes not already present in the file.
    """
    if not merged_diffs:
        return None

    # Compute project memory path
    home = Path.home()
    memory_dir = home / ".claude" / "projects" / f"-{os.path.expanduser('~').lstrip('/')}-{project.replace('/', '-')}" / "memory"
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        # Documented contract: None on failure. This call was the one unguarded
        # step in the function, so a read-only or permission-denied memory dir
        # raised out of a fail-soft helper and into the caller.
        print(f"failed to create memory dir {memory_dir}: {e}", file=sys.stderr)
        return None

    memory_file = memory_dir / "merged_changes.md"

    # Read existing content to avoid duplication
    existing_hashes = set()
    if memory_file.exists():
        try:
            content = memory_file.read_text(errors="replace")
            # Extract all commit hashes already recorded
            # Tolerate the older `- **commit_hash**: <sha>` form as well as the
            # plain one written below. The writer used to emit markdown bold and
            # this pattern did not allow for it, so NO hash was ever recognised as
            # already present: every run re-appended every entry and the memory
            # file doubled in size each time.
            for match in re.finditer(r"commit_hash\**:\s*([a-f0-9]+)", content):
                existing_hashes.add(match.group(1))
        except Exception:
            pass

    # Filter to new entries only
    new_diffs = [d for d in merged_diffs if d["commit_hash"] not in existing_hashes]
    if not new_diffs:
        return None

    # Build frontmatter
    frontmatter = f"""---
name: merged-changes-log
description: Recently merged agent branch diffs for operator context and reuse-first adaptation
metadata:
  type: reference
  updated_at: {datetime.datetime.utcnow().isoformat()}
---

"""

    # Append new entries
    entries = []
    for diff_info in new_diffs:
        entry = f"""## {diff_info['branch_name']} ({diff_info['commit_hash'][:8]})

- author_date: {diff_info['author_date']}
- commit_hash: {diff_info['commit_hash']}
- merge_message: {diff_info['merge_message']}
- files_changed: {len(diff_info['files'])}
- extracted_at: {diff_info['extracted_at']}

### Changed files
{chr(10).join(f"- {f}" for f in diff_info['files'][:50])}

### Diff (max 60k chars)

```diff
{diff_info['diff'][:60000]}
```

"""
        entries.append(entry)

    body = "\n".join(entries)

    # Write file (append if exists, create if not)
    try:
        if memory_file.exists():
            # Append entries only. Re-emitting the frontmatter here planted a
            # second `---` block halfway down the document on every append, which
            # any frontmatter parser reads as the end of the file.
            existing = memory_file.read_text(errors="replace")
            memory_file.write_text(existing + "\n" + body, encoding="utf-8")
        else:
            memory_file.write_text(frontmatter + body, encoding="utf-8")
        return str(memory_file)
    except Exception as e:
        print(f"failed to write memory file {memory_file}: {e}", file=sys.stderr)
        return None


def sync_project_memory(repo: str, project: Optional[str] = None, limit: int = 50) -> bool:
    """Extract merged diffs from repo and sync to project memory. Idempotent by commit hash.

    Args:
        repo: Path to git repository
        project: Project identifier (defaults to repo basename)
        limit: Max number of merge commits to scan

    Returns:
        True if any new diffs were written, False otherwise.
    """
    if not project:
        project = _normalize_project_path(repo)

    diffs = extract_merged_diffs(repo, limit=limit)
    if not diffs:
        return False

    path = write_memory_file(project, diffs)
    return path is not None


def stats(repo: str, limit: int = 50) -> dict:
    """Return statistics about available merged diffs."""
    branches = get_recent_merged_agent_branches(repo, limit=limit)
    return {
        "total_merge_commits": len(branches),
        "sample_branches": [b["branch_name"] for b in branches[:5]],
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", help="Git repository path")
    parser.add_argument("--project", help="Project identifier (defaults to repo name)")
    parser.add_argument("--limit", type=int, default=50, help="Max merge commits to scan")
    parser.add_argument("--stats", action="store_true", help="Print statistics and exit")
    parser.add_argument("--dry-run", action="store_true", help="Extract diffs but don't write memory")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"error: {repo} is not a directory", file=sys.stderr)
        sys.exit(1)

    if args.stats:
        s = stats(repo, limit=args.limit)
        print(json.dumps(s, indent=2))
        sys.exit(0)

    if args.dry_run:
        diffs = extract_merged_diffs(repo, limit=args.limit)
        for d in diffs:
            print(f"- {d['branch_name']} ({d['commit_hash'][:8]}): {len(d['files'])} files")
    else:
        ok = sync_project_memory(repo, project=args.project, limit=args.limit)
        sys.exit(0 if ok else 1)
