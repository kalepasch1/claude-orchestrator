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
import tempfile
import time


_DIR = os.path.dirname(os.path.abspath(__file__))
_HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
_STAMP_DIR = os.environ.get("ORCH_DEPS_STAMP_DIR", os.path.join(_HOME, "deps"))
_LOCKS = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock")

#: Files that configure the RESOLUTION, not just the dependency list.
#:
#: pnpm 10+ moved `overrides`, `allowBuilds`, `minimumReleaseAgeExclude` and
#: friends out of package.json and into pnpm-workspace.yaml. A snapshot built from
#: package.json + lockfile alone therefore has NO overrides while the lockfile
#: records them, and pnpm refuses the frozen install outright:
#:
#:   [ERR_PNPM_LOCKFILE_CONFIG_MISMATCH] Cannot proceed with the frozen
#:   installation. The current "overrides" configuration doesn't match the value
#:   found in the lockfile
#:
#: Found 2026-08-30: tomorrow pinned four transitive packages via
#: pnpm-workspace.yaml `overrides` in the 2026-08-18 vulnerability fix. Every
#: snapshot build for that repo has failed since, so every merge_train build gate
#: returned BUILDFAIL — "production build red; fix build/type errors before
#: merge" — on branches whose code was never the problem.
#:
#: These belong in the fingerprint too: changing an override changes the install,
#: so a snapshot keyed without them would be served stale after an edit.
_CONFIG_FILES = ("pnpm-workspace.yaml", "pnpm-workspace.yml",
                 ".pnpmfile.cjs", "pnpmfile.cjs", ".yarnrc.yml")
_DEFAULT_TIMEOUT = int(os.environ.get("ORCH_DEPS_PREWARM_TIMEOUT", "900"))
#: Resolved once. None means "this platform has no clonefile", which is every non-macOS
#: host and any macOS old enough not to export it — both fall through to `cp`.
_CLONEFILE = None
_CLONEFILE_PROBED = False


def _clonefile_fn():
    global _CLONEFILE, _CLONEFILE_PROBED
    if _CLONEFILE_PROBED:
        return _CLONEFILE
    _CLONEFILE_PROBED = True
    try:
        if os.uname().sysname != "Darwin":
            return None
        import ctypes, ctypes.util
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        fn = libc.clonefile
        fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        fn.restype = ctypes.c_int
        _CLONEFILE = fn
    except Exception:
        _CLONEFILE = None
    return _CLONEFILE


def _clonefile_dir(src, dst):
    """Clone a whole directory tree in one syscall. False means "use cp instead".

    Returns True only when the destination exists afterwards, so a partial or refused
    clone can never be mistaken for a warm node_modules — which would put the gate back
    into the state where every branch reported TESTFAIL for an unresolvable import.
    """
    if os.environ.get("ORCH_DEPS_CLONEFILE", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return False
    fn = _clonefile_fn()
    if fn is None or os.path.exists(dst):
        return False
    try:
        rc = fn(str(src).encode("utf-8"), str(dst).encode("utf-8"), 0)
    except Exception:
        return False
    if rc != 0 or not os.path.isdir(dst):
        # EXDEV (different volume), ENOTSUP (not APFS), EEXIST, anything else: leave no
        # half-built tree behind for the cp fallback to trip over.
        try:
            if os.path.exists(dst):
                shutil.rmtree(dst, ignore_errors=True)
        except Exception:
            pass
        return False
    return True


# Per-`cp` ceiling for one package root's node_modules activation.
_ACTIVATION_CALL_TIMEOUT_S = int(os.environ.get("ORCH_DEPS_ACTIVATION_TIMEOUT", "180"))
# Ceiling for ALL roots in one link_shared_runtime() call. Must stay comfortably
# below merge_train's 900s pass watchdog so activation can never consume the
# whole pass and leave nothing merged.
_ACTIVATION_TOTAL_BUDGET_S = int(os.environ.get("ORCH_DEPS_ACTIVATION_BUDGET", "420"))
# Below this much remaining budget, skip cloning and symlink instead.
_ACTIVATION_MIN_SLICE_S = int(os.environ.get("ORCH_DEPS_ACTIVATION_MIN_SLICE", "15"))
_COMMON_PACKAGE_DIRS = tuple(
    x.strip() for x in os.environ.get(
        "ORCH_PACKAGE_ROOT_HINTS",
        "web,app,frontend,client,dashboard,site,ui,mcp",
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


def _snapshot_dir():
    return os.environ.get("ORCH_DEPS_SNAPSHOT_DIR", os.path.join(_STAMP_DIR, "snapshots"))


def _fingerprint(repo):
    """Content address an install so incomplete/stale trees are never reused."""
    digest = hashlib.sha256()
    digest.update(os.uname().sysname.encode("utf-8"))
    digest.update(os.uname().machine.encode("utf-8"))
    for name in ("package.json", *_LOCKS, *_CONFIG_FILES, ".npmrc"):
        path = os.path.join(repo, name)
        if not os.path.isfile(path):
            continue
        digest.update(name.encode("utf-8"))
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _snapshot_path(repo):
    return os.path.join(_snapshot_dir(), _fingerprint(repo))


def _signature(repo):
    bits = []
    for name in ("package.json", *_LOCKS, *_CONFIG_FILES):
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


def _copy_local_dependencies(repo, build_root):
    """Stage manifest-declared file: dependencies without copying the whole repo."""
    try:
        with open(os.path.join(repo, "package.json"), encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return []
    copied = []
    deps = {}
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        deps.update(manifest.get(key) or {})
    repo_real = os.path.realpath(repo)
    for spec in deps.values():
        if not str(spec).startswith("file:"):
            continue
        rel = str(spec)[len("file:"):].strip()
        src = os.path.realpath(os.path.join(repo, rel))
        if not (src == repo_real or src.startswith(repo_real + os.sep)) or not os.path.exists(src):
            continue
        dst = os.path.join(build_root, os.path.relpath(src, repo_real))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        copied.append(rel)
    return copied


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


def _vercel_install_cmd(repo):
    """The install command the repo's own deploy uses, if it declares one.

    WHY THIS COMES FIRST.

    The picker below infers a manager from which lockfile is present, and a
    package-lock.json means `npm ci`. That is a good default and it is wrong
    whenever the project has already answered the question itself.

    smarter's vercel.json says `npm install --legacy-peer-deps`, and it says so
    because `npm ci` CANNOT run in that repo: the lockfile carries cac@7.0.0
    where a nested vite-node wants cac@6.7.14, and ci refuses a lockfile it
    considers out of sync. So every prewarm for that project failed at the
    install step — before a line of the app compiled — and the build gate
    reported a red that said nothing whatsoever about the commit. Vercel itself
    was building it green the whole time, because Vercel reads vercel.json.

    A gate that installs differently from the deploy is not testing the deploy.
    """
    try:
        with open(os.path.join(repo, "vercel.json"), encoding="utf-8") as f:
            declared = str(json.load(f).get("installCommand") or "").strip()
    except Exception:
        return None
    if not declared:
        return None
    return declared


def _manager(repo):
    declared_install = _vercel_install_cmd(repo)
    if declared_install:
        # Run it through the shell, as Vercel does — it is a command line, not argv.
        return "npm", ["bash", "-lc", declared_install]

    pnpm = shutil.which("pnpm") or _tool("pnpm")
    yarn = shutil.which("yarn") or _tool("yarn")
    npm = _tool("npm")
    try:
        with open(os.path.join(repo, "package.json"), encoding="utf-8") as f:
            declared = str(json.load(f).get("packageManager") or "").lower()
    except Exception:
        declared = ""
    has_npm = os.path.isfile(os.path.join(repo, "package-lock.json"))
    has_pnpm = os.path.isfile(os.path.join(repo, "pnpm-lock.yaml"))
    has_yarn = os.path.isfile(os.path.join(repo, "yarn.lock"))
    if declared.startswith("pnpm@") and has_pnpm and shutil.which("pnpm"):
        return "pnpm", [pnpm, "install", "--frozen-lockfile", "--prefer-offline"]
    if declared.startswith("yarn@") and has_yarn and shutil.which("yarn"):
        return "yarn", [yarn, "install", "--frozen-lockfile", "--prefer-offline"]
    if has_npm:
        return "npm", [npm, "ci", "--prefer-offline", "--no-audit", "--fund=false"]
    if has_pnpm and shutil.which("pnpm"):
        return "pnpm", [pnpm, "install", "--frozen-lockfile", "--prefer-offline"]
    if has_yarn and shutil.which("yarn"):
        return "yarn", [yarn, "install", "--frozen-lockfile", "--prefer-offline"]
    return "npm", [npm, "install", "--prefer-offline", "--no-audit", "--fund=false"]


def _dev_env(manager, cmd):
    """(cmd, env) that installs devDependencies, whatever NODE_ENV the fleet runs under.

    ROOT CAUSE, found 2026-08-12. This host exports NODE_ENV=production. npm reads that
    and OMITS devDependencies — silently, exiting 0, reporting "up to date". So every
    fleet install produced a tree with no vitest, no test runner, no dev tooling, and
    `npx vitest` died with ERR_MODULE_NOT_FOUND. worktree_preflight then called that tree
    a "partial install" and blocked the project, forever, because re-running the same
    install could never change the outcome.

    Measured in claude-orchestrator/web: `npm ci` added 622 packages and vitest was not
    among them; `npm ls vitest` reported empty while package.json declared it in
    devDependencies. Re-running with NODE_ENV=development and --include=dev added the
    missing 200 packages and the suite ran green immediately.

    The fleet installs in order to BUILD AND TEST, so dev dependencies are not optional
    for it — production omission is a deployment concern, not a CI one. Forced explicitly
    rather than by hoping the ambient environment is right.
    """
    env = dict(os.environ)
    if str(env.get("NODE_ENV", "")).lower() == "production":
        env["NODE_ENV"] = "development"
    env.pop("NPM_CONFIG_PRODUCTION", None)
    env["NPM_CONFIG_INCLUDE"] = "dev"
    # A shell form (["bash","-lc", "<command line>"]) must not be appended to as
    # argv — the flag would land on bash, not on npm. NPM_CONFIG_INCLUDE above
    # already carries the same instruction and npm reads it either way.
    shell_form = len(cmd) >= 2 and cmd[0].endswith("bash") and cmd[1] == "-lc"
    if manager == "npm" and not shell_form and "--include=dev" not in cmd:
        cmd = [*cmd, "--include=dev"]
    elif manager == "pnpm" and "--prod" not in cmd:
        cmd = [*cmd, "--dev"] if "--dev" not in cmd else cmd
    return cmd, env


def _ignore_scripts_cmd(manager, cmd):
    if manager == "npm" and "--ignore-scripts" not in cmd:
        return [*cmd, "--ignore-scripts"]
    if manager == "pnpm" and "--ignore-scripts" not in cmd:
        return [*cmd, "--ignore-scripts"]
    if manager == "yarn" and "--ignore-scripts" not in cmd:
        return [*cmd, "--ignore-scripts"]
    return None


def _entrypoint_files(pkg_dir, meta):
    """Relative entrypoint paths a package declares, as far as we can cheaply tell."""
    out = []
    for key in ("main", "module"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            out.append(val.strip())
    def _collect(node, depth=0):
        """Walk nested export conditions: {"import": {"default": "./src/index.js"}}."""
        if depth > 6:
            return
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for key in ("node", "import", "require", "default", "browser"):
                if key in node:
                    _collect(node[key], depth + 1)
        elif isinstance(node, list):
            for item in node:
                _collect(item, depth + 1)

    exports = meta.get("exports")
    if isinstance(exports, str):
        out.append(exports)
    elif isinstance(exports, dict):
        _collect(exports.get(".", exports))
    return [p for p in out if isinstance(p, str) and not p.startswith("#") and "*" not in p]


_ENTRY_EXTS = (".js", ".mjs", ".cjs", ".json", ".node", ".ts", ".d.ts")


def _resolves(pkg_dir, target):
    """Whether `target` resolves inside pkg_dir the way Node would.

    Manifests routinely declare extensionless entrypoints ("main": "./dist/index") or point at a
    directory. A bare os.path.exists() call marks all of those missing, which would flag most of
    a healthy tree as corrupt and send every checkout into a reinstall loop.
    """
    base = os.path.normpath(os.path.join(pkg_dir, target.lstrip("./") if target.startswith("./") else target))
    if os.path.isfile(base):
        return True
    for ext in _ENTRY_EXTS:
        if os.path.isfile(base + ext):
            return True
    if os.path.isdir(base):
        for ext in _ENTRY_EXTS:
            if os.path.isfile(os.path.join(base, "index" + ext)):
                return True
        # A directory that exists but has no index is still a real directory on disk; treat the
        # entrypoint as present and let the build be the judge rather than guessing wrong.
        return True
    return False


def broken_packages(repo, limit=25):
    """Installed packages whose directory exists but whose declared entrypoint does not.

    Concurrent npm/pnpm runs against one checkout leave exactly this shape: node_modules/<pkg>
    survives with its package.json, but dist/ was pruned by the other process. Nothing downstream
    notices — .bin symlinks still resolve — until the build dies with ERR_MODULE_NOT_FOUND for
    some transitive dependency. Scanning the top level is bounded (a few hundred stats) and cheap
    relative to the doomed build it prevents.
    """
    nm = os.path.join(repo, "node_modules")
    if not os.path.isdir(nm):
        return []
    broken = []
    try:
        entries = sorted(os.listdir(nm))
    except OSError:
        return []
    for name in entries:
        if name.startswith(".") or name == ".bin":
            continue
        base = os.path.join(nm, name)
        candidates = []
        if name.startswith("@"):
            try:
                candidates = [os.path.join(base, sub) for sub in sorted(os.listdir(base))]
            except OSError:
                continue
        else:
            candidates = [base]
        for pkg_dir in candidates:
            manifest = os.path.join(pkg_dir, "package.json")
            if not os.path.isfile(manifest):
                continue
            try:
                with open(manifest, encoding="utf-8") as fh:
                    meta = json.load(fh)
            except Exception:
                continue
            targets = _entrypoint_files(pkg_dir, meta)
            if not targets:
                continue
            # Only flag when *every* declared entrypoint is missing: packages legitimately ship
            # a subset (e.g. ESM-only builds that still declare a CJS "main").
            if all(not _resolves(pkg_dir, t) for t in targets):
                broken.append(os.path.relpath(pkg_dir, nm))
                if len(broken) >= limit:
                    return broken
    return broken


# Transitive packages the JS toolchains load on every build. A corrupt copy of any of these takes
# the build down with an ERR_MODULE_NOT_FOUND that names the transitive package, not the direct
# dependency, which is what made the 2026-08-02 corruption so slow to diagnose.
_RUNTIME_CRITICAL = frozenset({
    "citty", "consola", "std-env", "h3", "nitropack", "unstorage", "ofetch", "ufo", "defu",
    "pathe", "jiti", "unimport", "unplugin", "vite", "rollup", "esbuild", "webpack",
    "nuxt", "nuxi", "next", "typescript", "vue", "vue-router", "postcss", "tailwindcss",
})


def _load_bearing(repo, rel_pkg, manifest):
    """Whether a damaged package is one this build will actually try to load.

    Some packages are simply mispackaged upstream — the deprecated `fs` stub ships no index.js at
    all, and `javascript-opentimestamps` points `main` at a file it never publishes. Those have
    been "broken" since the day they were installed and the builds pass anyway. Failing readiness
    on them would put the checkout into a permanent reinstall loop, which is a worse outage than
    the one this check exists to catch — so direct dependencies deliberately do NOT qualify.

    Only the shared JS toolchain does. Those packages are correctly published, every build loads
    them, and they are precisely what a torn concurrent install damaged on 2026-08-02. If one of
    them has lost its entrypoint, the tree really is corrupt and reinstalling really is the fix.
    """
    name = rel_pkg.replace(os.sep, "/")
    return name in _RUNTIME_CRITICAL or name.split("/")[0] in ("@nuxt", "@vue", "@vitejs")


def _deps_ready_local(repo):
    if not os.path.isfile(os.path.join(repo, "package.json")):
        return True
    manifest = {}
    try:
        with open(os.path.join(repo, "package.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        # Only dependencies and devDependencies are installed INTO this package.
        #
        # peerDependencies are supplied by whoever consumes the package — npm
        # creates no node_modules for a package that merely declares one — and
        # optionalDependencies are, by definition, allowed to be absent.
        # Counting either as "this package must have an install" makes readiness
        # unsatisfiable forever: smarter/packages/smarter-core declares exactly
        # one optional peer (h3) and nothing else, so it had no node_modules,
        # was marked not-ready on every check, and failed prove_build for the
        # whole repo — over a package that was correctly installed by having
        # nothing to install.
        #
        # This is the second instance of this bug in this function. The tsconfig
        # one below has the same shape: a gate nothing can satisfy does not stop
        # bad builds, it manufactures repair work and the corruption that comes
        # with concurrent installs.
        declared_deps = any(manifest.get(k) for k in ("dependencies", "devDependencies"))
    except Exception:
        declared_deps = True
    nm = os.path.join(repo, "node_modules")
    # `npm ci` legitimately creates no node_modules directory for a zero-dependency
    # package. Treating that as broken caused infinite repair work for leaf packages.
    if not os.path.isdir(nm) and declared_deps:
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
    # Require the TypeScript CLI only when the project actually depends on it.
    #
    # FIX 2026-08-02: this used to fire on the mere presence of tsconfig.json. Nuxt generates a
    # tsconfig.json for editor support in projects that never install a standalone `typescript`
    # (pareto-2080 is one), so that checkout could never satisfy readiness. Every caller that
    # asked "are deps ready?" got False and kicked off another install — which is how several
    # agents ended up running npm/pnpm against the same node_modules at once and tearing it. The
    # never-satisfiable gate was manufacturing the corruption this module is meant to prevent.
    _declares_ts = any((manifest.get(k) or {}).get(dep)
                       for k in ("dependencies", "devDependencies")
                       for dep in ("typescript", "vue-tsc"))
    if "tsc" in joined or "typescript" in joined or _declares_ts:
        required_bins.append(("tsc", "vue-tsc"))
    if not os.path.isdir(nm):
        return not required_bins
    bin_dir = os.path.join(nm, ".bin")
    for choices in required_bins:
        if not any(os.path.exists(os.path.join(bin_dir, c)) for c in choices):
            return False
    # A launcher can survive a partial/pruned install while the module it imports
    # has disappeared. Nuxt then fails at startup with a misleading
    # ERR_MODULE_NOT_FOUND for @nuxt/cli/dist/index.mjs; the old check accepted
    # that tree because node_modules/.bin/nuxi still existed. Validate the small
    # set of runtime entrypoints that makes a Nuxt/Vue install actually usable.
    is_nuxt = any("nuxt" in group for group in required_bins)
    if is_nuxt:
        required_files = (
            ("@nuxt", "cli", "dist", "index.mjs"),
            ("@vue", "compiler-sfc", "dist", "compiler-sfc.cjs.js"),
        )
        if not all(os.path.isfile(os.path.join(nm, *parts)) for parts in required_files):
            return False
    # Catch the general case the two hardcoded probes above only sample: any package left
    # entrypoint-less by a concurrent install. Reporting not-ready sends this checkout back
    # through a reinstall instead of into a build that dies on ERR_MODULE_NOT_FOUND.
    if _truthy("ORCH_PREWARM_INTEGRITY_SCAN", True):
        damaged = [p for p in broken_packages(repo, limit=40) if _load_bearing(repo, p, manifest)]
        if damaged:
            print(f"dependency_prewarm: {repo} has {len(damaged)} load-bearing package(s) with "
                  f"missing entrypoints ({', '.join(damaged[:5])}); treating install as not ready")
            return False
    return True


def _ready_snapshot(repo):
    try:
        path = _snapshot_path(repo)
        if (os.path.isfile(os.path.join(path, ".ready.json"))
                and _deps_ready_local(path)):
            return path
    except Exception:
        pass
    return None


def deps_ready(repo):
    """Return True when either a local or immutable install is usable."""
    return _deps_ready_local(repo) or bool(_ready_snapshot(repo))


def _stamp_matches(repo):
    return bool(_ready_snapshot(repo))


def ensure(repo, reason="prewarm", timeout=None):
    """Build and atomically publish an immutable dependency snapshot."""
    if not _truthy("ORCH_PREWARM_INSTALL_DEPS", True):
        return {"ok": True, "skipped": "disabled"}
    if not repo or not os.path.isdir(repo):
        return {"ok": True, "skipped": "missing-repo"}
    if not os.path.isfile(os.path.join(repo, "package.json")):
        return {"ok": True, "skipped": "no-package-json"}
    if _stamp_matches(repo):
        return {"ok": True, "skipped": "warm-cache"}
    # Two locks, two jobs. The manifest-keyed lock below collapses identical installs across
    # worktrees into one build. It deliberately does NOT provide mutual exclusion per checkout —
    # two installs against the same tree with different manifest states take different locks — so
    # take the checkout-keyed lock as well before touching this repo's dependencies.
    _checkout_lock = None
    try:
        import install_lock as _il
        _checkout_lock = _il.hold(repo, reason=reason)
        _checkout_lock.__enter__()
    except Exception:
        _checkout_lock = None
    try:
        return _ensure_locked(repo, reason=reason, timeout=timeout)
    finally:
        if _checkout_lock is not None:
            try:
                _checkout_lock.__exit__(None, None, None)
            except Exception:
                pass


def _ensure_locked(repo, reason="prewarm", timeout=None):
    # The lock is keyed by manifest content rather than checkout path: identical installs
    # across worktrees collapse into one build and one immutable runtime.
    lock_file = None
    build_root = None
    try:
        import fcntl as _fcntl
        os.makedirs(_snapshot_dir(), exist_ok=True)
        lock_file = open(_snapshot_path(repo) + ".lock", "w")
        _fcntl.flock(lock_file, _fcntl.LOCK_EX)
        if _stamp_matches(repo):
            lock_file.close()
            return {"ok": True, "skipped": "warm-cache (installed by concurrent process)"}
    except Exception:
        pass  # locking is best-effort; proceed unlocked rather than fail the warm
    try:
        os.makedirs(_snapshot_dir(), exist_ok=True)
        build_root = tempfile.mkdtemp(prefix=_fingerprint(repo) + ".building-",
                                      dir=_snapshot_dir())
        # vercel.json comes along because _vercel_install_cmd reads it. Without it
        # the staging dir looks like a bare package.json + lockfile, _manager
        # infers `npm ci`, and the project's own declared installCommand is lost.
        for name in ("package.json", *_LOCKS, *_CONFIG_FILES, ".npmrc", "vercel.json"):
            src = os.path.join(repo, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(build_root, name))
        prisma = os.path.join(repo, "prisma")
        if os.path.isdir(prisma):
            shutil.copytree(prisma, os.path.join(build_root, "prisma"))
        schema = os.path.join(repo, "schema.prisma")
        if os.path.isfile(schema):
            shutil.copy2(schema, os.path.join(build_root, "schema.prisma"))
        _copy_local_dependencies(repo, build_root)
    except Exception as e:
        if build_root:
            shutil.rmtree(build_root, ignore_errors=True)
        if lock_file:
            lock_file.close()
        return {"ok": False, "error": f"snapshot staging failed: {e}"}
    # _manager(repo), NOT _manager(build_root).
    #
    # The install command is a property of the PROJECT, not of the temporary
    # directory we stage into. build_root holds only package.json, the lockfile
    # and .npmrc, so _vercel_install_cmd found no vercel.json there, returned
    # None, and the lockfile-based fallback chose `npm ci` — for smarter, whose
    # vercel.json declares `npm install --legacy-peer-deps` precisely BECAUSE
    # npm ci cannot run against its lockfile (cac@7.0.0 vs a nested
    # vite-node wanting cac@6.7.14). Every prewarm for that project failed at
    # the install step, so prove_build reported a red that said nothing about
    # the commit, while Vercel built the same tree green because Vercel reads
    # vercel.json.
    #
    # Both halves matter: the copy above so anything else in build_root can see
    # it, and reading from `repo` so the decision does not depend on staging.
    manager, cmd = _manager(repo)
    # The fleet installs in order to build AND TEST, so devDependencies are mandatory for
    # it. See _dev_env: NODE_ENV=production on this host was silently omitting them.
    cmd, _env = _dev_env(manager, cmd)
    try:
        r = subprocess.run(cmd, cwd=build_root, capture_output=True, text=True,
                           env=_env, timeout=timeout or _DEFAULT_TIMEOUT)
    except subprocess.TimeoutExpired:
        shutil.rmtree(build_root, ignore_errors=True)
        if lock_file: lock_file.close()
        return {"ok": False, "manager": manager, "error": f"install timed out after {timeout or _DEFAULT_TIMEOUT}s"}
    except Exception as e:
        shutil.rmtree(build_root, ignore_errors=True)
        if lock_file: lock_file.close()
        return {"ok": False, "manager": manager, "error": str(e)}
    ignored_scripts = False
    if r.returncode != 0 and _truthy("ORCH_PREWARM_IGNORE_SCRIPTS_FALLBACK", True):
        fallback = _ignore_scripts_cmd(manager, cmd)
        if fallback:
            r2 = subprocess.run(fallback, cwd=build_root, capture_output=True, text=True,
                                env=_env, timeout=timeout or _DEFAULT_TIMEOUT)
            if r2.returncode == 0:
                r = r2
                ignored_scripts = True
    if r.returncode != 0:
        tail = ((r.stdout or "")[-800:] + "\n" + (r.stderr or "")[-800:]).strip()
        err = tail or f"{manager} install failed"
        # A failed install leaves the snapshot unready; label it with the standard
        # readiness-validation failure class so repair routing sees one error family.
        try:
            if not _deps_ready_local(build_root):
                err = "installed snapshot failed dependency readiness validation: " + err
        except Exception:
            pass
        shutil.rmtree(build_root, ignore_errors=True)
        if lock_file: lock_file.close()
        return {"ok": False, "manager": manager, "error": err[:2000]}
    # PRISMA (2026-07-14): installs that skip lifecycle scripts (--ignore-scripts fallback,
    # pnpm script whitelisting) never run `prisma generate`, so every test importing the client
    # fails with "Cannot find module '.prisma/client/default'" — this single missing step
    # accounted for 49 red test files on tomorrow's staging. Generate explicitly when a schema
    # exists; harmless no-op otherwise.
    try:
        if (os.path.isfile(os.path.join(build_root, "prisma", "schema.prisma"))
                or os.path.isfile(os.path.join(build_root, "schema.prisma"))):
            npx = shutil.which("npx") or "npx"
            subprocess.run([npx, "prisma", "generate"], cwd=build_root, capture_output=True,
                           text=True, timeout=300)
    except Exception:
        pass
    if not _deps_ready_local(build_root):
        shutil.rmtree(build_root, ignore_errors=True)
        if lock_file: lock_file.close()
        return {"ok": False, "manager": manager,
                "error": "installed snapshot failed dependency readiness validation"}
    final_root = _snapshot_path(repo)
    try:
        with open(os.path.join(build_root, ".ready.json"), "w", encoding="utf-8") as f:
            json.dump({"source": os.path.realpath(repo), "fingerprint": _fingerprint(repo),
                       "manager": manager, "reason": reason, "ignored_scripts": ignored_scripts,
                       "updated_at": time.time()}, f)
        if os.path.isdir(final_root):
            shutil.rmtree(build_root, ignore_errors=True)
        else:
            os.replace(build_root, final_root)
        build_root = None
    except Exception as e:
        shutil.rmtree(build_root, ignore_errors=True)
        if lock_file: lock_file.close()
        return {"ok": False, "manager": manager, "error": f"snapshot publish failed: {e}"}
    os.makedirs(_STAMP_DIR, exist_ok=True)
    try:
        with open(_stamp_path(repo), "w", encoding="utf-8") as f:
            json.dump({"repo": os.path.realpath(repo), "signature": _signature(repo),
                       "manager": manager, "reason": reason, "ignored_scripts": ignored_scripts,
                       "updated_at": time.time()}, f)
    except Exception:
        pass
    if lock_file: lock_file.close()
    return {"ok": bool(_ready_snapshot(repo)), "manager": manager, "installed": True,
            "ignored_scripts": ignored_scripts, "snapshot": final_root}


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


def runtime_root(repo):
    """Return the immutable warmed runtime when available, else the repo."""
    return _ready_snapshot(repo) or repo


def link_shared_runtime(repo, worktree):
    """Reuse warmed node_modules/env files in an ephemeral worktree.

    This intentionally mirrors the package-root discovery above so nested apps
    get their own dependency symlinks instead of falling back to missing CLIs.
    """
    roots = package_roots(repo) or [repo]
    linked = []

    # Aggregate wall-clock budget for the clone path.
    #
    # activate_modules() bounds each individual `cp` at _ACTIVATION_CALL_TIMEOUT_S,
    # but this function calls it once per package root. With 6 roots (the current
    # beethoven layout) the worst case was 6 * 180s = 1080s, which alone exceeds the
    # 900s merge_train watchdog -- so a single _build_gate could burn the entire pass
    # in dependency activation and get killed before integrating anything. Bound the
    # total here and degrade to the (near-instant) symlink path once spent.
    deadline = time.monotonic() + _ACTIVATION_TOTAL_BUDGET_S

    def link_one(src, dst):
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                os.symlink(src, dst)
                linked.append(dst)
            except Exception:
                pass

    def activate_modules(src, dst):
        if not os.path.isdir(src) or os.path.exists(dst):
            return
        mode = os.environ.get("ORCH_DEPS_ACTIVATION_MODE", "clone").lower()
        remaining = deadline - time.monotonic()
        # ONE SYSCALL INSTEAD OF 76,928 OF THEM.
        #
        # `cp -cR` clones each file individually, so its cost is the FILE COUNT of a
        # node_modules, not its size. macOS clonefile(2) clones a whole directory
        # hierarchy in a single call. Measured on tomorrow's node_modules (76,928
        # files) on 2026-09-01: cp -cR 46.3s, clonefile 5.5s, identical file count and
        # the copies read back the same. Under real fleet load the same step was timed
        # at 136.9s per merge candidate, and it is paid again in full on every redo.
        #
        # Same semantics as cp -c: copy-on-write, an independent tree that shares
        # blocks until written. Every failure path falls through to the cp below, so a
        # non-APFS volume, a cross-filesystem destination or an older kernel behaves
        # exactly as before.
        if (mode == "clone" and remaining > _ACTIVATION_MIN_SLICE_S
                and _clonefile_dir(src, dst)):
            linked.append(dst)
            return
        if mode == "clone" and remaining > _ACTIVATION_MIN_SLICE_S:
            if os.uname().sysname == "Darwin":
                cmd = ["cp", "-cR", src, dst]
            else:
                cmd = ["cp", "-a", "--reflink=auto", src, dst]
            try:
                copied = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=min(_ACTIVATION_CALL_TIMEOUT_S, remaining),
                )
                if copied.returncode == 0 and os.path.isdir(dst):
                    linked.append(dst)
                    return
            except Exception:
                pass
            shutil.rmtree(dst, ignore_errors=True)
        link_one(src, dst)

    for shared in (".env", ".env.local"):
        link_one(os.path.join(repo, shared), os.path.join(worktree, shared))

    for root in roots:
        rel = os.path.relpath(root, repo)
        target_root = worktree if rel == "." else os.path.join(worktree, rel)
        if not os.path.isdir(target_root):
            continue
        snapshot = _ready_snapshot(root)
        modules = os.path.join(snapshot, "node_modules") if snapshot else os.path.join(root, "node_modules")
        activate_modules(modules, os.path.join(target_root, "node_modules"))
        for shared in (".env", ".env.local"):
            link_one(os.path.join(root, shared), os.path.join(target_root, shared))
    return linked
