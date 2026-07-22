#!/usr/bin/env python3
from __future__ import annotations
"""
output_recycling.py — Agent output recycling (100X retry savings).

When an agent produces partial correct work before failing, extract and cache
the correct portions. The next attempt starts from the partial work instead
of scratch.

What gets recycled:
  1. Files successfully created/modified (in the worktree)
  2. Plans and approaches that were on the right track
  3. Test results (what passed, what failed)
  4. Dependency analysis (what files are related)

Combined with session_cache (which caches metadata), this module caches actual
file-level work product.

Usage:
    import output_recycling
    # After a failure:
    output_recycling.recycle(task_id, worktree, agent_output, error)
    # Before a retry:
    recycled = output_recycling.get_recycled(task_id)
    if recycled:
        prompt = output_recycling.inject_recycled(prompt, recycled)
"""
import os, sys, json, subprocess, hashlib, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_RECYCLED_FILES = int(os.environ.get("ORCH_RECYCLE_MAX_FILES", "5"))
MAX_RECYCLED_CONTENT = int(os.environ.get("ORCH_RECYCLE_MAX_CONTENT", "3000"))
RECYCLE_TTL_H = float(os.environ.get("ORCH_RECYCLE_TTL_H", "12"))


def _recycled_store():
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.output_recycling"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_store(store):
    # Prune expired
    cutoff = time.time() - RECYCLE_TTL_H * 3600
    store = {k: v for k, v in store.items() if v.get("timestamp", 0) > cutoff}
    if len(store) > 100:
        by_time = sorted(store.items(), key=lambda x: x[1].get("timestamp", 0))
        store = dict(by_time[-100:])
    try:
        db.upsert("controls", {"key": "output_recycling", "value": json.dumps(store, default=str)})
    except Exception:
        pass


def _extract_modified_files(worktree, base_ref="HEAD"):
    """Extract files that were modified in the worktree since base."""
    modified = []
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref],
            cwd=worktree, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            modified = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception:
        pass

    # Also check untracked files
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=worktree, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            untracked = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            modified.extend(untracked)
    except Exception:
        pass

    return modified[:MAX_RECYCLED_FILES * 2]


def _read_file_content(worktree, filepath, max_chars=1000):
    """Read file content from worktree."""
    try:
        fullpath = os.path.join(worktree, filepath)
        if os.path.isfile(fullpath) and os.path.getsize(fullpath) < 50000:
            with open(fullpath, "r", errors="replace") as f:
                return f.read()[:max_chars]
    except Exception:
        pass
    return None


def recycle(task_id, worktree, agent_output, error="", base_ref="HEAD"):
    """Extract and cache reusable work from a failed agent run.

    Call this after an agent failure, before the worktree is cleaned up.
    """
    store = _recycled_store()

    # Extract modified files
    modified = _extract_modified_files(worktree, base_ref)

    # Read content of modified files (the partial work)
    file_contents = {}
    total_chars = 0
    for f in modified[:MAX_RECYCLED_FILES]:
        content = _read_file_content(worktree, f, max_chars=MAX_RECYCLED_CONTENT // MAX_RECYCLED_FILES)
        if content:
            file_contents[f] = content
            total_chars += len(content)
            if total_chars >= MAX_RECYCLED_CONTENT:
                break

    # Extract what tests passed/failed from output
    output = agent_output or ""
    test_results = []
    for line in output.split("\n"):
        if re.search(r"(PASS|FAIL|✓|✗|×)", line):
            test_results.append(line.strip()[:100])

    # Extract the approach used
    approach = ""
    approach_match = re.search(r"(?:plan|approach|strategy):\s*(.+?)(?:\n\n|\Z)", output, re.S | re.I)
    if approach_match:
        approach = approach_match.group(1)[:500]

    entry = {
        "task_id": task_id,
        "timestamp": time.time(),
        "modified_files": modified[:MAX_RECYCLED_FILES],
        "file_contents": file_contents,
        "test_results": test_results[:10],
        "approach": approach,
        "error": (error or "")[:300],
        "output_tail": output[-500:],
    }

    store[task_id] = entry
    _save_store(store)
    return entry


def get_recycled(task_id):
    """Get recycled work from a prior failed attempt."""
    store = _recycled_store()
    return store.get(task_id)


def inject_recycled(prompt, recycled):
    """Inject recycled work context into a retry prompt."""
    if not recycled:
        return prompt

    injection = "\n\n## RECYCLED WORK FROM PRIOR ATTEMPT\n"
    injection += "The previous attempt produced partial work. Build on it.\n\n"

    # Error context
    error = recycled.get("error", "")
    if error:
        injection += f"**Previous error:** {error[:200]}\n\n"

    # Approach used (to try something different)
    approach = recycled.get("approach", "")
    if approach:
        injection += f"**Prior approach (FAILED):** {approach[:300]}\n"
        injection += "Try a DIFFERENT approach.\n\n"

    # Partial file work
    contents = recycled.get("file_contents", {})
    if contents:
        injection += "**Partial work in worktree (may be usable):**\n"
        for filepath, content in list(contents.items())[:3]:
            injection += f"\n`{filepath}` (partial):\n```\n{content[:500]}\n```\n"

    # Test results
    tests = recycled.get("test_results", [])
    if tests:
        injection += f"\n**Test results from prior attempt:**\n"
        for t in tests[:5]:
            injection += f"  {t}\n"

    # Cap injection size
    if len(injection) > MAX_RECYCLED_CONTENT:
        injection = injection[:MAX_RECYCLED_CONTENT] + "\n...(truncated)\n"

    return injection + "\n" + prompt


def run():
    """Periodic: prune expired recycled data."""
    store = _recycled_store()
    before = len(store)
    cutoff = time.time() - RECYCLE_TTL_H * 3600
    store = {k: v for k, v in store.items() if v.get("timestamp", 0) > cutoff}
    after = len(store)
    if before != after:
        _save_store(store)
    print(f"[output-recycling] {after} cached ({before - after} pruned)")
