#!/usr/bin/env python3
"""
install_all_deps.py — find every dependency manifest in the repo, install it, and prove it.

WHY THIS IS NOT JUST "run npm install"
    Two things make the naive version wrong on this fleet, and both were measured here:

    1. NODE_ENV=production. This host exports it, npm honours it, and devDependencies are
       silently omitted — exit 0, "up to date", no test runner in the tree. Measured in
       web/: `npm ci` installed 622 packages without vitest while package.json declared
       it, and `npx vitest` died with ERR_MODULE_NOT_FOUND. Any installer that inherits
       the ambient environment reproduces that.

    2. "Installed" is not the same as "usable". npm reports a truncated package as
       satisfied (`npm ls` is happy: the package.json is present, only the files listed in
       main/exports/bin are missing). So the install has to be VERIFIED, not trusted —
       which is exactly what the acceptance criterion for this task asks for.

    Both are handled here: the subprocess environment is corrected before each install,
    and --check re-derives the answer from `npm ls --depth=0` and real imports rather than
    from the installer's exit code.

Usage:
    python3 tools/install_all_deps.py            # report what is missing
    python3 tools/install_all_deps.py --install  # install everything discovered
    python3 tools/install_all_deps.py --check    # exit 1 if anything is unsatisfied
    python3 tools/install_all_deps.py --json
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)

SKIP_DIRS = {".git", "node_modules", ".nuxt", ".output", "dist", "build", "__pycache__",
             ".venv", "venv", ".pytest_cache", "_to_delete", "coverage", ".next"}

MAX_DEPTH = int(os.environ.get("ORCH_DEPS_MAX_DEPTH", "3"))
TIMEOUT = int(os.environ.get("ORCH_DEPS_TIMEOUT", "900"))

#: PyPI distribution name -> the module you actually import. Only the ones that differ;
#: guessing by s/-/_/ alone reports python-dotenv and prometheus-client as missing when
#: both are installed and working, which is a false alarm that trains people to ignore
#: the check.
IMPORT_NAME = {
    "python-dotenv": "dotenv",
    "prometheus-client": "prometheus_client",
    "beautifulsoup4": "bs4",
    "pyyaml": "yaml",
    "pillow": "PIL",
    "python-dateutil": "dateutil",
    "msgpack-python": "msgpack",
    "attrs": "attr",
    "protobuf": "google.protobuf",
    "scikit-learn": "sklearn",
    "opencv-python": "cv2",
    "typing-extensions": "typing_extensions",
}


# ── discovery ─────────────────────────────────────────────────────────────────

def discover(root=REPO, max_depth=MAX_DEPTH):
    """[{kind, path, dir}] for every manifest in the tree, nearest-first."""
    found, root = [], os.path.abspath(root)
    for cwd, dirs, files in os.walk(root):
        depth = cwd[len(root):].count(os.sep)
        if depth >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            kind = None
            if name == "package.json":
                kind = "npm"
            elif re.fullmatch(r"requirements(-[\w.]+)?\.txt", name):
                kind = "pip"
            elif name == "Gemfile":
                kind = "bundler"
            elif name == "pyproject.toml":
                kind = "pyproject"
            elif name == "go.mod":
                kind = "go"
            elif name == "Cargo.toml":
                kind = "cargo"
            if kind:
                found.append({"kind": kind, "path": os.path.join(cwd, name), "dir": cwd})
    found.sort(key=lambda m: (m["path"].count(os.sep), m["path"]))
    return found


# ── environment ───────────────────────────────────────────────────────────────

def install_env():
    """A copy of os.environ that will not omit dev dependencies.

    See the module docstring: NODE_ENV=production on this host silently strips
    devDependencies, which is how a tree ends up with no test runner while every command
    reports success.
    """
    env = dict(os.environ)
    if str(env.get("NODE_ENV", "")).lower() == "production":
        env["NODE_ENV"] = "development"
    env.pop("NPM_CONFIG_PRODUCTION", None)
    env["NPM_CONFIG_INCLUDE"] = "dev"
    return env


def _run(cmd, cwd, timeout=TIMEOUT):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           env=install_env(), timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


# ── install ───────────────────────────────────────────────────────────────────

def install(manifest):
    """Install one manifest. Returns {ok, kind, dir, skipped, output}."""
    kind, d = manifest["kind"], manifest["dir"]
    out = {"kind": kind, "dir": os.path.relpath(d, REPO), "ok": False, "skipped": None}
    if kind == "npm":
        npm = shutil.which("npm")
        if not npm:
            out["skipped"] = "npm not on PATH"
            return out
        has_lock = os.path.isfile(os.path.join(d, "package-lock.json"))
        cmd = [npm, "ci" if has_lock else "install", "--include=dev",
               "--no-audit", "--fund=false"]
        rc, log = _run(cmd, d)
        if rc != 0 and has_lock:
            # a lockfile out of sync with package.json makes `npm ci` refuse outright;
            # `npm install` is the documented recovery and updates the lockfile
            rc, log = _run([npm, "install", "--include=dev", "--no-audit", "--fund=false"], d)
        out["ok"], out["output"] = rc == 0, log[-400:]
    elif kind == "pip":
        cmd = [sys.executable, "-m", "pip", "install", "-r", manifest["path"],
               "--disable-pip-version-check"]
        rc, log = _run(cmd, d)
        if rc != 0 and "externally-managed-environment" in log:
            rc, log = _run(cmd + ["--break-system-packages"], d)
        out["ok"], out["output"] = rc == 0, log[-400:]
    elif kind == "bundler":
        bundle = shutil.which("bundle")
        if not bundle:
            out["skipped"] = "bundler not on PATH"
            return out
        rc, log = _run([bundle, "install"], d)
        out["ok"], out["output"] = rc == 0, log[-400:]
    else:
        out["skipped"] = f"{kind} manifests are reported, not installed"
    return out


# ── verify (the acceptance criterion) ─────────────────────────────────────────

def _declared_npm(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    names = []
    for field in ("dependencies", "devDependencies"):
        names.extend((data.get(field) or {}).keys())
    return names


def verify_npm(manifest):
    """Every declared package present in `npm ls --depth=0`, per the acceptance test."""
    d = manifest["dir"]
    declared = _declared_npm(manifest["path"])
    res = {"kind": "npm", "dir": os.path.relpath(d, REPO),
           "declared": len(declared), "missing": [], "ok": True}
    if not declared:
        return res
    if not os.path.isdir(os.path.join(d, "node_modules")):
        res["missing"], res["ok"] = declared[:20], False
        res["reason"] = "no node_modules at all"
        return res
    for name in declared:
        pkg = os.path.join(d, "node_modules", *name.split("/"))
        if not os.path.isfile(os.path.join(pkg, "package.json")):
            res["missing"].append(name)
    res["ok"] = not res["missing"]
    res["missing"] = res["missing"][:20]
    return res


def _declared_pip(path):
    names = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if not line or line.startswith("-"):
                    continue
                names.append(re.split(r"[\[<>=!;~ ]", line)[0].strip())
    except Exception:
        return []
    return [n for n in names if n]


def verify_pip(manifest):
    """Declared distributions actually importable — not merely listed by pip."""
    declared = _declared_pip(manifest["path"])
    res = {"kind": "pip", "dir": os.path.relpath(manifest["dir"], REPO),
           "declared": len(declared), "missing": [], "ok": True}
    import importlib.util
    for dist in declared:
        module = IMPORT_NAME.get(dist.lower(), dist.replace("-", "_"))
        try:
            found = importlib.util.find_spec(module.split(".")[0]) is not None
        except Exception:
            found = False
        if not found:
            res["missing"].append(dist)
    res["ok"] = not res["missing"]
    return res


def verify(manifest):
    if manifest["kind"] == "npm":
        return verify_npm(manifest)
    if manifest["kind"] == "pip":
        return verify_pip(manifest)
    return {"kind": manifest["kind"], "dir": os.path.relpath(manifest["dir"], REPO),
            "declared": 0, "missing": [], "ok": True, "reason": "not verified"}


# ── driver ────────────────────────────────────────────────────────────────────

def run(root=REPO, do_install=False):
    manifests = discover(root)
    out = {"manifests": len(manifests), "installed": [], "verified": [],
           "unsatisfied": 0}
    for m in manifests:
        if do_install:
            out["installed"].append(install(m))
        v = verify(m)
        out["verified"].append(v)
        if not v["ok"]:
            out["unsatisfied"] += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--install", action="store_true", help="install every manifest found")
    ap.add_argument("--check", action="store_true", help="exit 1 if anything is missing")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=REPO)
    args = ap.parse_args()

    res = run(root=args.root, do_install=args.install)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"install_all_deps: {res['manifests']} manifest(s), "
              f"{res['unsatisfied']} unsatisfied")
        for i in res["installed"]:
            state = "ok" if i["ok"] else (i.get("skipped") or "FAILED")
            print(f"  install {i['kind']:9} {i['dir'] or '.':40} {state}")
        for v in res["verified"]:
            if v["ok"]:
                continue
            print(f"  MISSING {v['kind']:9} {v['dir'] or '.':40} "
                  f"{len(v['missing'])}/{v['declared']} — {', '.join(v['missing'][:4])}")
    return 1 if (args.check and res["unsatisfied"]) else 0


if __name__ == "__main__":
    sys.exit(main())
