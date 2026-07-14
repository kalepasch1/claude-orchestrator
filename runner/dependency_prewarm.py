#!/usr/bin/env python3
"""Best-effort per-repo dependency prewarm for faster green merges.

The build gate intentionally runs from fresh worktrees, but most JavaScript
repos can share the root repo's installed dependencies. This module keeps that
root install warm and stamp-cached so missing CLIs (nuxt/nuxi/next/vite/etc.)
fail far less often during integration.
"""
import hashlib
import json
import os
import shutil
import subprocess
import time


_DIR = os.path.dirname(os.path.abspath(__file__))
_HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
_STAMP_DIR = os.environ.get("ORCH_DEPS_STAMP_DIR", os.path.join(_HOME, "deps"))
_LOCKS = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock")
_DEFAULT_TIMEOUT = int(os.environ.get("ORCH_DEPS_PREWARM_TIMEOUT", "900"))
_COMMON_PACKAGE_DIRS = tuple(
    x.strip() for x in os.environ.get(
        "ORCH_PACKAGE_ROOT_HINTS",
        "web,app,frontend,client,dashboard,site,ui",
    ).split(",") if x.strip()
)
_PACKAGE_PARENT_DIRS = ("apps", "packages", "services")
_TOOL_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)


def _ensure_tool_path():
    path = os.environ.get("PATH", "")
    parts = [p for p in path.split(os.pathsep) if p]
    changed = False
    for p in _TOOL_PATHS:
        if os.path.isdir(p) and p not in parts:
            parts.insert(0, p)
            changed = True
    if changed:
        os.environ["PATH"] = os.pathsep.join(parts)


def _tool(name):
    _ensure_tool_path()
    return shutil.which(name) or name


def _truthy(name, default=True):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _repo_key(repo):
    return hashlib.sha1(os.path.realpath(repo).encode("utf-8")).hexdigest()


def _stamp_path(repo):
    return os.path.join(_STAMP_DIR, _repo_key(repo) + ".json")


def _signature(repo):
    bits = []
    for name in ("package.json", *_LOCKS):
        path = os.path.join(repo, name)
        if os.path.exists(path):
            st = os.stat(path)
            bits.append([name, int(st.st_mtime), st.st_size])
    return bits


def _load_scripts(repo):
    try:
        with open(os.path.join(repo, "package.json"), encoding="utf-8") as f:
            return (json.load(f).get("scripts") or {})
    except Exception:
        return {}


def _has_package(root):
    return os.path.isfile(os.path.join(root, "package.json"))


def package_roots(repo):
    """Return package roots worth warming/building, including common nested app dirs.

    Several linked apps keep the deployable package under `web/` or `apps/*`.
    Treating the repository root as the only package root made the release train
    misclassify those apps as "no package" and then run stale root commands.
    """
    if not repo or not os.path.isdir(repo):
        return []
    roots = []
    if _has_package(repo):
        roots.append(repo)
    for name in _COMMON_PACKAGE_DIRS:
        path = os.path.join(repo, name)
        if _has_package(path):
            roots.append(path)
    for parent in _PACKAGE_PARENT_DIRS:
        base = os.path.join(repo, parent)
        if not os.path.isdir(base):
            continue
        try:
            for child in sorted(os.listdir(base)):
                path = os.path.join(base, child)
                if os.path.isdir(path) and _has_package(path):
                    roots.append(path)
        except OSError:
            continue
    seen = set()
    out = []
    for root in roots:
        real = os.path.realpath(root)
        if real in seen:
            continue
        seen.add(real)
        out.append(root)
    return out


def _manager(repo):
    pnpm = shutil.which("pnpm") or _tool("pnpm")
    yarn = shutil.which("yarn") or _tool("yarn")
    npm = _tool("npm")
    if os.path.isfile(os.path.join(repo, "pnpm-lock.yaml")) and shutil.which("pnpm"):
        return "pnpm", [pnpm, "install", "--frozen-lockfile", "--prefer-offline"]
    if os.path.isfile(os.path.join(repo, "yarn.lock")) and shutil.which("yarn"):
        return "yarn", [yarn, "install", "--frozen-lockfile", "--prefer-offline"]
    if os.path.isfile(os.path.join(repo, "package-lock.json")):
        return "npm", [npm, "ci", "--prefer-offline", "--no-audit", "--fund=false"]
    return "npm", [npm, "install", "--prefer-offline", "--no-audit", "--fund=false"]


def _ignore_scripts_cmd(manager, cmd):
    if manager == "npm" and "--ignore-scripts" not in cmd:
        return [*cmd, "--ignore-scripts"]
    if manager == "pnpm" and "--ignore-scripts" not in cmd:
        return [*cmd, "--ignore-scripts"]
    if manager == "yarn" and "--ignore-scripts" not in cmd:
        return [*cmd, "--ignore-scripts"]
    return None


def deps_ready(repo):
    """Return True when the root install looks usable for local build worktrees."""
    if not os.path.isfile(os.path.join(repo, "package.json")):
        return True
    nm = os.path.join(repo, "node_modules")
    if not os.path.isdir(nm):
        return False
    scripts = _load_scripts(repo)
    joined = " ".join(str(v).lower() for v in scripts.values())
    required_bins = []
    if "nuxt" in joined or os.path.exists(os.path.join(repo, "nuxt.config.ts")) or os.path.exists(os.path.join(repo, "nuxt.config.js")):
        required_bins.append(("nuxt", "nuxi"))
    if "next" in joined or os.path.exists(os.path.join(repo, "next.config.js")) or os.path.exists(os.path.join(repo, "next.config.mjs")):
        required_bins.append(("next",))
    if "vite" in joined or os.path.exists(os.path.join(repo, "vite.config.ts")) or os.path.exists(os.path.join(repo, "vite.config.js")):
        required_bins.append(("vite",))
    if "tsc" in joined or "typescript" in joined or os.path.exists(os.path.join(repo, "tsconfig.json")):
        required_bins.append(("tsc", "vue-tsc"))
    bin_dir = os.path.join(nm, ".bin")
    for choices in required_bins:
        if not any(os.path.exists(os.path.join(bin_dir, c)) for c in choices):
            return False
    return True


def _stamp_matches(repo):
    try:
        with open(_stamp_path(repo), encoding="utf-8") as f:
            stamp = json.load(f)
        return stamp.get("signature") == _signature(repo) and deps_ready(repo)
    except Exception:
        return False


def ensure(repo, reason="prewarm", timeout=None):
    """Install dependencies once per repo signature. Returns a small result dict."""
    if not _truthy("ORCH_PREWARM_INSTALL_DEPS", True):
        return {"ok": True, "skipped": "disabled"}
    if not repo or not os.path.isdir(repo):
        return {"ok": True, "skipped": "missing-repo"}
    if not os.path.isfile(os.path.join(repo, "package.json")):
        return {"ok": True, "skipped": "no-package-json"}
    if _stamp_matches(repo):
        return {"ok": True, "skipped": "warm-cache"}
    # SERIALIZE INSTALLS (2026-07-14): multiple daemons (prewarm, build_daemon, executors) used
    # to run `npm install` in the SAME package root concurrently, corrupting node_modules
    # (ENOTDIR/ENOTEMPTY, half-extracted packages, poisoned npm cache). Take an exclusive
    # per-root flock; whoever waited re-checks the stamp and skips if another process warmed it.
    lock_file = None
    try:
        import fcntl as _fcntl
        os.makedirs(_STAMP_DIR, exist_ok=True)
        lock_file = open(_stamp_path(repo) + ".lock", "w")
        _fcntl.flock(lock_file, _fcntl.LOCK_EX)
        if _stamp_matches(repo):
            lock_file.close()
            return {"ok": True, "skipped": "warm-cache (installed by concurrent process)"}
    except Exception:
        pass  # locking is best-effort; proceed unlocked rather than fail the warm
    manager, cmd = _manager(repo)
    try:
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                           timeout=timeout or _DEFAULT_TIMEOUT)
    except subprocess.TimeoutExpired:
        if lock_file: lock_file.close()
        return {"ok": False, "manager": manager, "error": f"install timed out after {timeout or _DEFAULT_TIMEOUT}s"}
    except Exception as e:
        if lock_file: lock_file.close()
        return {"ok": False, "manager": manager, "error": str(e)}
    ignored_scripts = False
    if r.returncode != 0 and _truthy("ORCH_PREWARM_IGNORE_SCRIPTS_FALLBACK", True):
        fallback = _ignore_scripts_cmd(manager, cmd)
        if fallback:
            r2 = subprocess.run(fallback, cwd=repo, capture_output=True, text=True,
                                timeout=timeout or _DEFAULT_TIMEOUT)
            if r2.returncode == 0:
                r = r2
                ignored_scripts = True
    if r.returncode != 0:
        tail = ((r.stdout or "")[-800:] + "\n" + (r.stderr or "")[-800:]).strip()
        if lock_file: lock_file.close()
        return {"ok": False, "manager": manager, "error": tail or f"{manager} install failed"}
    os.makedirs(_STAMP_DIR, exist_ok=True)
    try:
        with open(_stamp_path(repo), "w", encoding="utf-8") as f:
            json.dump({"repo": os.path.realpath(repo), "signature": _signature(repo),
                       "manager": manager, "reason": reason, "ignored_scripts": ignored_scripts,
                       "updated_at": time.time()}, f)
    except Exception:
        pass
    if lock_file: lock_file.close()
    return {"ok": deps_ready(repo), "manager": manager, "installed": True,
            "ignored_scripts": ignored_scripts}


def ensure_all(repo, reason="prewarm", timeout=None):
    """Warm every package root in a repo and return an aggregate result."""
    roots = package_roots(repo)
    if not roots:
        return ensure(repo, reason=reason, timeout=timeout)
    results = []
    ok = True
    for root in roots:
        rel = os.path.relpath(root, repo)
        res = ensure(root, reason=f"{reason}:{rel}", timeout=timeout)
        res = dict(res or {})
        res["root"] = "." if rel == "." else rel
        results.append(res)
        ok = ok and bool(res.get("ok"))
    failed = next((r for r in results if not r.get("ok")), None)
    return {"ok": ok, "roots": results, "count": len(results),
            "error": failed.get("error") if failed else None}


def link_shared_runtime(repo, worktree):
    """Reuse warmed node_modules/env files in an ephemeral worktree.

    This intentionally mirrors the package-root discovery above so nested apps
    get their own dependency symlinks instead of falling back to missing CLIs.
    """
    roots = package_roots(repo) or [repo]
    linked = []

    def link_one(src, dst):
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                os.symlink(src, dst)
                linked.append(dst)
            except Exception:
                pass

    for shared in (".env", ".env.local"):
        link_one(os.path.join(repo, shared), os.path.join(worktree, shared))

    for root in roots:
        rel = os.path.relpath(root, repo)
        target_root = worktree if rel == "." else os.path.join(worktree, rel)
        if not os.path.isdir(target_root):
            continue
        for shared in ("node_modules", ".env", ".env.local"):
            link_one(os.path.join(root, shared), os.path.join(target_root, shared))
    return linked
