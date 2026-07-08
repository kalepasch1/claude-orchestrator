#!/usr/bin/env python3
"""
build_gate.py - the fix for "merges succeed but every Vercel deploy fails". Before any branch merges to
a prod branch, run the project's REAL production build in an isolated worktree. Only branches whose build
is GREEN are allowed to merge — so build-breaking code can never reach main/master again.

Fast + safe: symlinks the main repo's node_modules into the ephemeral worktree (no reinstall), runs the
detected build (prefers typecheck when present — catches the TS/Nuxt errors that break Vercel — else the
full build), with a timeout. Returns (ok, log). Auto-detects build_cmd from package.json and caches it on
the project row.
"""
import os, sys, json, subprocess, tempfile, shutil, shlex
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import dependency_prewarm


def _load_scripts(root):
    try:
        with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
            return (json.load(f).get("scripts") or {})
    except Exception:
        return {}


def script_cmd(repo, package_root, script):
    """Return a shell command that runs a package script from the repo root."""
    rel = os.path.relpath(package_root, repo)
    mgr = _package_runner(package_root)
    if rel == ".":
        return f"{mgr} {script}"
    qrel = shlex.quote(rel)
    if mgr == "pnpm":
        return f"pnpm --dir {qrel} {script}"
    if mgr == "yarn":
        return f"yarn --cwd {qrel} {script}"
    return f"npm --prefix {qrel} run {script}"


def _npx_cmd(repo, package_root, command):
    rel = os.path.relpath(package_root, repo)
    if rel == ".":
        return f"npx --no-install {command}"
    return f"cd {shlex.quote(rel)} && npx --no-install {command}"


def _root_npm_cmd_without_package(repo, cmd):
    if os.path.isfile(os.path.join(repo, "package.json")):
        return False
    cmd = str(cmd or "").strip()
    return cmd.startswith(("npm run ", "npm test", "yarn ", "pnpm ", "npx "))


def detect_build_cmd(repo):
    """Prefer a fast typecheck (catches most Vercel build breaks), else the real build."""
    roots = dependency_prewarm.package_roots(repo)
    if not roots:
        return os.environ.get("DEFAULT_BUILD_CMD", "")
    for root in roots:
        scripts = _load_scripts(root)
        for s in ("typecheck", "type-check", "tsc", "build"):
            if s in scripts:
                return script_cmd(repo, root, s)
        # Nuxt/Next default even without a script.
        if (os.path.isfile(os.path.join(root, "nuxt.config.ts"))
                or os.path.isfile(os.path.join(root, "nuxt.config.js"))):
            return _npx_cmd(repo, root, "nuxi typecheck")
        if os.path.isfile(os.path.join(root, "next.config.js")) or os.path.isfile(os.path.join(root, "next.config.mjs")):
            return _npx_cmd(repo, root, "next build")
        if scripts:
            return script_cmd(repo, root, "build")
    return ""


def _package_runner(repo):
    """Return an installed package-manager script runner.

    Lockfiles reveal the author's preferred manager, but the runner machine may not have
    that CLI installed. Falling back to npm is better than blocking every branch with
    `yarn: command not found` / `pnpm: command not found`.
    """
    if os.path.isfile(os.path.join(repo, "pnpm-lock.yaml")) and shutil.which("pnpm"):
        return "pnpm"
    if os.path.isfile(os.path.join(repo, "yarn.lock")) and shutil.which("yarn"):
        return "yarn"
    return "npm run"


def build_cmd_for(project_row, repo):
    cmd = project_row.get("build_cmd")
    detected = detect_build_cmd(repo)
    if cmd and _root_npm_cmd_without_package(repo, cmd) and detected:
        db.update("projects", {"name": project_row.get("name")}, {"build_cmd": detected})
        return detected
    if cmd:
        return cmd
    if detected:
        db.update("projects", {"name": project_row.get("name")}, {"build_cmd": detected})
    return detected


def run_build(repo, branch, build_cmd, timeout=600):
    """Green-build check of `branch` in an ephemeral worktree. Returns (ok, log)."""
    if not build_cmd:
        return True, "no build_cmd (skipped)"     # nothing to check -> don't block
    if os.environ.get("ORCH_BUILD_GATE_INSTALL_DEPS", "true").lower() in ("true", "1", "yes", "on"):
        warmed = dependency_prewarm.ensure_all(repo, reason="build_gate")
        if not warmed.get("ok"):
            return False, "dependency prewarm failed: " + (warmed.get("error") or str(warmed))[-1200:]
    tmp = tempfile.mkdtemp(prefix="build-")
    try:
        if subprocess.run(["git", "worktree", "add", "-f", tmp, branch],
                          cwd=repo, capture_output=True).returncode != 0:
            return False, "could not create build worktree"
        # Reuse warmed deps/env for the root and nested package apps.
        dependency_prewarm.link_shared_runtime(repo, tmp)
        r = subprocess.run(["bash", "-lc", build_cmd], cwd=tmp, capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        log = ((r.stdout or "")[-5000:] + "\n" + (r.stderr or "")[-5000:]).strip()
        return ok, log
    except subprocess.TimeoutExpired:
        return False, f"build timed out (>{timeout}s)"
    except Exception as e:
        return False, f"build error: {e}"
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", tmp], cwd=repo, capture_output=True, timeout=60)
        shutil.rmtree(tmp, ignore_errors=True)


def check(project_name, branch):
    p = (db.select("projects", {"select": "*", "name": f"eq.{project_name}"}) or [{}])[0]
    repo = p.get("repo_path", "")
    if not repo or not os.path.isdir(repo):
        return True, "repo not on this machine (skipped)"
    return run_build(repo, branch, build_cmd_for(p, repo))


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        ok, log = check(sys.argv[1], sys.argv[2])
        print("BUILD", "GREEN" if ok else "RED"); print(log[:800])
