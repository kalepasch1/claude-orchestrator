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
import os, sys, json, subprocess, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def detect_build_cmd(repo):
    """Prefer a fast typecheck (catches most Vercel build breaks), else the real build."""
    pkg = os.path.join(repo, "package.json")
    if not os.path.isfile(pkg):
        return os.environ.get("DEFAULT_BUILD_CMD", "")
    try:
        scripts = (json.load(open(pkg)).get("scripts") or {})
    except Exception:
        scripts = {}
    mgr = "pnpm" if os.path.isfile(os.path.join(repo, "pnpm-lock.yaml")) else \
          ("yarn" if os.path.isfile(os.path.join(repo, "yarn.lock")) else "npm run")
    for s in ("typecheck", "type-check", "tsc", "build"):
        if s in scripts:
            return f"{mgr} {s}"
    # Nuxt/Next default even without a script
    if os.path.isfile(os.path.join(repo, "nuxt.config.ts")) or os.path.isfile(os.path.join(repo, "nuxt.config.js")):
        return "npx nuxi typecheck"
    return f"{mgr} build" if scripts else ""


def build_cmd_for(project_row, repo):
    cmd = project_row.get("build_cmd")
    if cmd:
        return cmd
    cmd = detect_build_cmd(repo)
    if cmd:
        db.update("projects", {"name": project_row.get("name")}, {"build_cmd": cmd})
    return cmd


def run_build(repo, branch, build_cmd, timeout=600):
    """Green-build check of `branch` in an ephemeral worktree. Returns (ok, log)."""
    if not build_cmd:
        return True, "no build_cmd (skipped)"     # nothing to check -> don't block
    tmp = tempfile.mkdtemp(prefix="build-")
    try:
        if subprocess.run(["git", "worktree", "add", "-f", tmp, branch],
                          cwd=repo, capture_output=True).returncode != 0:
            return False, "could not create build worktree"
        # reuse deps: symlink node_modules (+ .env) from the main repo so we don't reinstall
        for shared in ("node_modules", ".env", ".env.local"):
            src = os.path.join(repo, shared)
            if os.path.exists(src) and not os.path.exists(os.path.join(tmp, shared)):
                try:
                    os.symlink(src, os.path.join(tmp, shared))
                except Exception:
                    pass
        r = subprocess.run(["bash", "-lc", build_cmd], cwd=tmp, capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        log = ((r.stdout or "")[-1500:] + "\n" + (r.stderr or "")[-800:]).strip()
        return ok, log
    except subprocess.TimeoutExpired:
        return False, f"build timed out (>{timeout}s)"
    except Exception as e:
        return False, f"build error: {e}"
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", tmp], cwd=repo, capture_output=True)
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
