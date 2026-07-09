#!/usr/bin/env python3
"""
warm_pool.py - Eliminates per-task cold-start by maintaining a small pool of pre-warmed
context slots per active repo. Each slot holds the pre-loaded CLAUDE.md content as a
context prefix that is injected into the prompt before the Claude CLI is invoked, so the
agent starts with project context already present instead of discovering it fresh each call.

Pool size is bounded by WARM_POOL_SIZE and gated by resource_governor.can_claim() so it
shrinks automatically under RAM pressure. Falls back silently to '' (cold start) when the
pool is exhausted or unhealthy — callers need no special handling.

Usage:
    from warm_pool import acquire, preload, invalidate, stats

    # In runner/runner.py after claiming a task:
    ctx = warm_pool.acquire(repo_path)
    result = claude_cli.run(ctx + task_prompt, model, cwd=repo_path, ...)

    # At runner startup to eagerly warm active repos:
    warm_pool.preload([p["repo_path"] for p in active_projects])

    # After a git pull changes CLAUDE.md:
    warm_pool.invalidate(repo_path)
"""
import os, sys, time, threading, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

POOL_SIZE        = int(os.environ.get("WARM_POOL_SIZE",        "3"))
SLOT_TTL         = int(os.environ.get("WARM_POOL_TTL_S",       "300"))   # 5 min freshness
CONTEXT_MAX_BYTES= int(os.environ.get("WARM_POOL_CTX_BYTES",   "8192"))
HEALTH_INTERVAL  = int(os.environ.get("WARM_POOL_HEALTH_S",    "60"))

_CLAUDE_MD_NAMES = ("CLAUDE.md", ".claude/CLAUDE.md")


class _Slot:
    """One warm context entry for a single repo path."""
    __slots__ = ("repo", "context_prefix", "loaded_at", "checksum", "hits")

    def __init__(self, repo, context_prefix, checksum):
        self.repo           = repo
        self.context_prefix = context_prefix
        self.loaded_at      = time.time()
        self.checksum       = checksum
        self.hits           = 0

    def age(self):
        return time.time() - self.loaded_at

    def is_stale(self):
        return self.age() > SLOT_TTL

    def is_healthy(self):
        """Confirm CLAUDE.md on disk still matches what we loaded."""
        try:
            cur = _read_claude_md(self.repo)
            return _checksum(cur) == self.checksum
        except Exception:
            return False


def _read_claude_md(repo):
    for name in _CLAUDE_MD_NAMES:
        p = os.path.join(repo, name)
        try:
            with open(p, "r", errors="replace") as f:
                return f.read()[:CONTEXT_MAX_BYTES]
        except FileNotFoundError:
            continue
        except Exception:
            return ""
    return ""


def _checksum(text):
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _build_context(repo):
    """Build a compact context prefix from the repo's CLAUDE.md. Returns (prefix, checksum)."""
    md = _read_claude_md(repo)
    if not md.strip():
        return "", _checksum("")
    prefix = f"# Project context (pre-loaded)\n\n{md.strip()}\n\n---\n\n"
    return prefix[:CONTEXT_MAX_BYTES], _checksum(md)


class WarmPool:
    """
    Thread-safe, memory-aware pool of pre-loaded context slots keyed by repo path.
    One instance is shared across the runner process via the module-level singleton.
    """

    def __init__(self, pool_size=None):
        self._size       = pool_size if pool_size is not None else POOL_SIZE
        self._slots      = {}           # repo_path -> _Slot
        self._lock       = threading.Lock()
        self._last_health= 0.0
        self._enabled    = True

    # ── Public API ────────────────────────────────────────────────────────────

    def acquire(self, repo):
        """Return a context prefix string for *repo*, or '' on miss / error.
        Thread-safe. Never raises — callers append it to their prompt or ignore it."""
        if not self._enabled or not repo:
            return ""
        try:
            self._maybe_health_sweep()
            with self._lock:
                slot = self._slots.get(repo)
                if slot and not slot.is_stale():
                    slot.hits += 1
                    return slot.context_prefix
            # Cache miss or stale — warm synchronously (fast: just disk reads)
            self._warm_one(repo)
            with self._lock:
                slot = self._slots.get(repo)
                if slot:
                    slot.hits += 1
                    return slot.context_prefix
                return ""
        except Exception:
            return ""   # fail-soft: pool failures never break the runner

    def preload(self, repos):
        """Eagerly warm a list of repos (call at runner startup). Respects pool size/memory."""
        for r in (repos or []):
            try:
                self._warm_one(r)
            except Exception:
                pass

    def invalidate(self, repo):
        """Drop a repo's slot so the next acquire re-reads from disk."""
        with self._lock:
            self._slots.pop(repo, None)

    def stats(self):
        with self._lock:
            return {
                "pool_size": self._size,
                "loaded":    len(self._slots),
                "enabled":   self._enabled,
                "repos": [
                    {"repo": os.path.basename(r), "age_s": round(s.age()), "hits": s.hits}
                    for r, s in self._slots.items()
                ],
            }

    def set_enabled(self, enabled):
        self._enabled = enabled
        if not enabled:
            with self._lock:
                self._slots.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _mem_ok(self):
        """Gate pool expansion on resource_governor; fail-open if unavailable."""
        try:
            import resource_governor
            ok, _ = resource_governor.can_claim()
            return ok
        except Exception:
            return True

    def _warm_one(self, repo):
        """Load or refresh a slot for *repo*. No-op if already fresh, or resources too low."""
        if not repo or not os.path.isdir(repo):
            return
        with self._lock:
            existing = self._slots.get(repo)
            if existing and not existing.is_stale():
                return
            # Pool full and adding a new repo → need to evict; check memory first
            if len(self._slots) >= self._size and repo not in self._slots:
                if not self._mem_ok():
                    return
                oldest = min(self._slots, key=lambda r: self._slots[r].loaded_at, default=None)
                if oldest:
                    del self._slots[oldest]
        # Build context outside the lock (disk I/O)
        prefix, cs = _build_context(repo)
        with self._lock:
            # Re-enforce size limit: concurrent threads may have inserted while we were on disk.
            if repo not in self._slots:
                while len(self._slots) >= self._size:
                    oldest = min(self._slots, key=lambda r: self._slots[r].loaded_at)
                    del self._slots[oldest]
            self._slots[repo] = _Slot(repo, prefix, cs)

    def _maybe_health_sweep(self):
        now = time.time()
        if now - self._last_health < HEALTH_INTERVAL:
            return
        self._last_health = now
        with self._lock:
            stale = [r for r, s in self._slots.items() if s.is_stale() or not s.is_healthy()]
        for r in stale:
            with self._lock:
                self._slots.pop(r, None)


# Module-level singleton — one pool per runner process
_pool = WarmPool()


def acquire(repo):
    """Acquire a context prefix for *repo* from the singleton pool."""
    return _pool.acquire(repo)


def preload(repos):
    _pool.preload(repos)


def invalidate(repo):
    _pool.invalidate(repo)


def stats():
    return _pool.stats()


if __name__ == "__main__":
    import json
    print(json.dumps(stats(), indent=2))
