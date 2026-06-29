#!/usr/bin/env python3
"""
caching.py - prompt-caching helper. The big input-token lever is reusing a STABLE
context prefix across tasks so it gets cached (Claude Code caches the system/context
prefix automatically; identical bytes => cache hit => up to ~90% input savings on the
shared portion).

We build one deterministic prefix per repo from CLAUDE.md + a conventions block and
prepend it byte-identically to every task in that repo. Keep it stable: changing it
busts the cache, so only update conventions deliberately.
"""
import os, hashlib

def load_prefix(repo_path):
    parts = []
    for fn in ("CLAUDE.md", ".claude/CONVENTIONS.md", "CONVENTIONS.md"):
        p = os.path.join(repo_path, fn)
        if os.path.isfile(p):
            try:
                parts.append(open(p, errors="replace").read())
            except Exception:
                pass
    if not parts:
        return ""
    prefix = ("# Project context (cached - do not restate, just apply):\n\n"
              + "\n\n".join(parts) + "\n\n# ---- task ----\n")
    return prefix

def prefix_id(prefix):
    return hashlib.sha256(prefix.encode()).hexdigest()[:12] if prefix else "none"
