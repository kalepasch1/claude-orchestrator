#!/usr/bin/env python3
"""
build_cache.py — cache node_modules + .nuxt artifacts keyed by lockfile hash.

Before a build, call restore(worktree) to hard-link a cached node_modules/.nuxt
into the worktree (if the lockfile hash matches). After a green build, call
save(worktree) to snapshot the artifacts for reuse by later tasks.

Behavior-preserving: a cache miss simply falls back to a clean build.
"""
import hashlib, os, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CACHE_ROOT = os.environ.get(
    "BUILD_CACHE_DIR",
    os.path.join(os.path.expanduser("~"), ".claude-orchestrator", "build-cache"),
)

LOCKFILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml")
CACHED_DIRS = ("node_modules", ".nuxt")


def cache_key(worktree: str) -> str:
    """Compute a stable SHA-256 from lockfile contents in *worktree*.

    If multiple lockfiles exist they are hashed in sorted order so the key is
    deterministic.  Returns empty string when no lockfile is found (cache miss).
    """
    h = hashlib.sha256()
    found = False
    for name in sorted(LOCKFILES):
        path = os.path.join(worktree, name)
        if not os.path.isfile(path):
            # also check web/ subdirectory
            path = os.path.join(worktree, "web", name)
            if not os.path.isfile(path):
                continue
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            found = True
        except OSError:
            continue
    return h.hexdigest() if found else ""


def _cache_dir_for(key: str) -> str:
    return os.path.join(CACHE_ROOT, key)


def restore(worktree: str, *, root: str | None = None) -> bool:
    """Restore cached build artifacts into *worktree*.  Returns True on hit."""
    key = cache_key(worktree)
    if not key:
        return False
    cache = _cache_dir_for(key) if root is None else os.path.join(root, key)
    if not os.path.isdir(cache):
        return False
    restored = False
    for dirname in CACHED_DIRS:
        src = os.path.join(cache, dirname)
        dst = os.path.join(worktree, "web", dirname) if dirname != "node_modules" else os.path.join(worktree, "web", dirname)
        # node_modules lives in web/ for this repo
        if not os.path.isdir(src):
            continue
        if os.path.exists(dst):
            shutil.rmtree(dst, ignore_errors=True)
        try:
            shutil.copytree(src, dst, symlinks=True)
            restored = True
        except OSError:
            pass
    return restored


def save(worktree: str, *, root: str | None = None) -> bool:
    """Snapshot build artifacts from *worktree* into the cache.  Returns True on success."""
    key = cache_key(worktree)
    if not key:
        return False
    cache = _cache_dir_for(key) if root is None else os.path.join(root, key)
    os.makedirs(cache, exist_ok=True)
    saved = False
    for dirname in CACHED_DIRS:
        src = os.path.join(worktree, "web", dirname)
        dst = os.path.join(cache, dirname)
        if not os.path.isdir(src):
            continue
        if os.path.exists(dst):
            shutil.rmtree(dst, ignore_errors=True)
        try:
            shutil.copytree(src, dst, symlinks=True)
            saved = True
        except OSError:
            pass
    return saved
