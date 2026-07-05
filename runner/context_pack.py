#!/usr/bin/env python3
"""
context_pack.py - give the headless drafter the same orientation a human has in an interactive session:
a compact repo map + the project's own conventions (CLAUDE.md / AGENTS.md). Cuts wasted turns spent
re-discovering where things live and how the codebase does things, which lifts first-pass quality.

Pure filesystem read (no model tokens). The block is stable per project, so it's a natural prompt-cache
prefix (claude_cli can wrap it in cache_control to cut input tokens ~5-10x across a project's tasks).
Fail-soft: returns '' on any problem.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_CONV_FILES = ("CLAUDE.md", "AGENTS.md", ".cursorrules", "CONTRIBUTING.md")


def _repo_map(repo, max_entries=120):
    """A compact tree of tracked files (dirs + notable files), from git so it respects .gitignore."""
    try:
        files = subprocess.run(["git", "-C", repo, "ls-files"], capture_output=True, text=True,
                               timeout=15).stdout.splitlines()
    except Exception:
        return ""
    # summarize: count files per top-2-level dir, list key entrypoints
    from collections import Counter
    dirs = Counter()
    keys = []
    for f in files:
        parts = f.split("/")
        top = "/".join(parts[:2]) if len(parts) > 1 else parts[0]
        dirs[top] += 1
        base = parts[-1].lower()
        if base in ("package.json", "nuxt.config.ts", "next.config.js", "vite.config.ts",
                    "tsconfig.json", "schema.prisma") or f.startswith("supabase/migrations"):
            keys.append(f)
    lines = ["repo map (files per area):"]
    for d, n in dirs.most_common(max_entries):
        lines.append(f"  {d}/  ({n})")
    if keys:
        lines.append("key files: " + ", ".join(sorted(set(keys))[:20]))
    return "\n".join(lines)


def _conventions(repo, max_chars=2500):
    for name in _CONV_FILES:
        p = os.path.join(repo, name)
        if os.path.isfile(p):
            try:
                return f"# project conventions ({name}):\n" + open(p, encoding="utf-8", errors="replace").read()[:max_chars]
            except Exception:
                pass
    return ""


def block(repo):
    """Return the injectable context block, or '' if disabled/unavailable."""
    if os.environ.get("ORCH_CONTEXT_PACK", "true").lower() not in ("true", "1", "yes"):
        return ""
    if not repo or not os.path.isdir(repo):
        return ""
    rm = _repo_map(repo)
    cv = _conventions(repo)
    if not rm and not cv:
        return ""
    return ("\n\n---\nREPO ORIENTATION (use it; don't re-discover):\n" + rm + ("\n\n" + cv if cv else "")).strip()


if __name__ == "__main__":
    print(block(os.environ.get("REPO", ".")))
