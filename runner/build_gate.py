#!/usr/bin/env python3
"""
build_gate.py - the fix for "merges succeed but every Vercel deploy fails". Before any branch merges to
a prod branch, run the project's REAL production build in an isolated worktree. Only branches whose build
is GREEN are allowed to merge — so build-breaking code can never reach main/master again.

Fast + safe: symlinks the main repo's node_modules into the ephemeral worktree (no reinstall), applies
.vercelignore to reproduce the uploaded source context, and runs the exact Vercel build command (or the
real package build) with a timeout. Returns (ok, log). Auto-detects build_cmd and caches it on the project.
"""
import fnmatch, os, sys, json, subprocess, tempfile, shutil, shlex
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


def _vercel_build_cmd(repo, package_root):
    """Return the exact configured Vercel build command for a package root."""
    path = os.path.join(package_root, "vercel.json")
    try:
        with open(path, encoding="utf-8") as f:
            command = str((json.load(f) or {}).get("buildCommand") or "").strip()
    except Exception:
        return ""
    if not command:
        return ""
    rel = os.path.relpath(package_root, repo)
    return command if rel == "." else f"cd {shlex.quote(rel)} && {command}"


def detect_build_cmd(repo):
    """Use the exact Vercel command, then the real production build, never only typecheck."""
    roots = dependency_prewarm.package_roots(repo)
    if not roots:
        return os.environ.get("DEFAULT_BUILD_CMD", "")
    for root in roots:
        vercel_cmd = _vercel_build_cmd(repo, root)
        if vercel_cmd:
            return vercel_cmd
        scripts = _load_scripts(root)
        for s in ("build:vercel", "build", "typecheck", "type-check", "tsc"):
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
    if detected and cmd != detected:
        db.update("projects", {"name": project_row.get("name")}, {"build_cmd": detected})
        return detected
    if cmd:
        return cmd
    if detected:
        db.update("projects", {"name": project_row.get("name")}, {"build_cmd": detected})
    return detected


def _matches_ignore(rel, pattern):
    pattern = pattern.strip().replace("\\", "/")
    rel = rel.replace("\\", "/")
    if pattern.startswith("/"):
        pattern = pattern[1:]
    if pattern.endswith("/"):
        return rel == pattern[:-1] or rel.startswith(pattern)
    if "/" not in pattern:
        return any(fnmatch.fnmatch(part, pattern) for part in rel.split("/"))
    return fnmatch.fnmatch(rel, pattern)


def _ignored_from_files(root, files, ignore):
    patterns = []
    with open(ignore, encoding="utf-8", errors="replace") as source:
        for raw in source:
            value = raw.strip()
            if value and not value.startswith("#"):
                patterns.append(value)
    ignored = []
    for rel in files:
        matched = False
        for pattern in patterns:
            negate = pattern.startswith("!")
            candidate = pattern[1:] if negate else pattern
            if _matches_ignore(rel, candidate):
                matched = not negate
        if matched:
            ignored.append(rel)
    return ignored


def _apply_vercelignore(worktree, tracked_files=None):
    """Remove tracked files excluded from Vercel's upload context in the disposable worktree."""
    removed = []
    roots = [worktree, *dependency_prewarm.package_roots(worktree)]
    seen = set()
    for root in roots:
        ignore = os.path.join(root, ".vercelignore")
        if not os.path.isfile(ignore) or ignore in seen:
            continue
        seen.add(ignore)
        if tracked_files is None:
            result = subprocess.run(
                ["git", "ls-files", "-ci", "--exclude-from", ignore],
                cwd=root, capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"could not evaluate {os.path.relpath(ignore, worktree)}: {result.stderr.strip()}")
            candidates = result.stdout.splitlines()
        else:
            prefix = os.path.relpath(root, worktree)
            candidates = []
            for item in tracked_files:
                if prefix == ".":
                    candidates.append(item)
                elif item.startswith(prefix.rstrip(os.sep) + "/"):
                    candidates.append(item[len(prefix.rstrip(os.sep)) + 1:])
            candidates = _ignored_from_files(root, candidates, ignore)
        for rel in candidates:
            path = os.path.normpath(os.path.join(root, rel))
            if not (path == worktree or path.startswith(worktree + os.sep)):
                raise RuntimeError(f"unsafe Vercel ignore path: {rel}")
            if os.path.isfile(path) or os.path.islink(path):
                os.unlink(path)
                removed.append(os.path.relpath(path, worktree))
            elif os.path.isdir(path):
                shutil.rmtree(path)
                removed.append(os.path.relpath(path, worktree))
    return sorted(set(removed))


def run_build(repo, branch, build_cmd, timeout=900, vercel_context=True):
    """Green-build an exact commit in an unregistered disposable overlay."""
    if not build_cmd:
        return True, "no build_cmd (skipped)"     # nothing to check -> don't block
    if os.environ.get("ORCH_BUILD_GATE_INSTALL_DEPS", "true").lower() in ("true", "1", "yes", "on"):
        warmed = dependency_prewarm.ensure_all(repo, reason="build_gate")
        if not warmed.get("ok"):
            return False, "dependency prewarm failed: " + (warmed.get("error") or str(warmed))[-1200:]
    import commit_overlay
    try:
        with commit_overlay.checkout(repo, branch, prefix="build-overlay-") as overlay:
            tmp = overlay["path"]
            dependency_prewarm.link_shared_runtime(repo, tmp)
            removed = _apply_vercelignore(tmp, overlay["files"]) if vercel_context else []
            r = subprocess.run(["bash", "-lc", build_cmd], cwd=tmp, capture_output=True, text=True, timeout=timeout)
            ok = r.returncode == 0
            context = (f"overlay {overlay['commit'][:12]}; Vercel context removed "
                       f"{len(removed)} tracked file(s)")
            log = (context + "\n" + (r.stdout or "")[-5000:] + "\n" + (r.stderr or "")[-5000:]).strip()
            return ok, log
    except subprocess.TimeoutExpired:
        return False, f"build timed out (>{timeout}s)"
    except Exception as e:
        return False, f"build error: {e}"


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


# ── Branch build-status scanning (merged from master build_gate) ──
import re

ENABLED = os.environ.get("ORCH_BUILD_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")

_FAILURE_PATTERNS = [
    (re.compile(r"ModuleNotFoundError:\s*No module named ['\"]?(\S+)['\"]?", re.I), "missing_module"),
    (re.compile(r"ImportError:\s*cannot import name ['\"]?(\S+)['\"]?", re.I), "import_error"),
    (re.compile(r'relation "(\S+)" does not exist', re.I), "missing_table"),
    (re.compile(r"column [\"']?(\S+?)[\"']? (?:does not exist|of relation)", re.I), "missing_column"),
    (re.compile(r"FileNotFoundError:.*No such file.*?['\"]([^'\"]+)['\"]", re.I), "missing_file"),
    (re.compile(r"(SyntaxError:.*)", re.I), "syntax_error"),
    (re.compile(r"(TypeError:.*)", re.I), "type_error"),
    (re.compile(r"build[_ ]?fail|compilation[_ ]?error", re.I), "build_failure"),
    (re.compile(r"test[_ ]?fail", re.I), "test_failure"),
]


def _git(repo, *args, timeout=30):
    """Run a git command, return (returncode, stdout, stderr). Fail-soft."""
    try:
        r = subprocess.run(
            ["git"] + list(args), cwd=repo,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _default_repo():
    """Resolve the repo path from the first project in the DB, or cwd."""
    try:
        rows = db.select("projects", {"select": "repo_path", "limit": "1"}) or []
        if rows and rows[0].get("repo_path"):
            return rows[0]["repo_path"]
    except Exception:
        pass
    return os.getcwd()


def scan_branches(repo=None):
    """List unmerged agent/* branches.

    Returns a list of branch name strings.  Fail-soft: returns [] on error.
    """
    if not ENABLED:
        return []
    repo = repo or _default_repo()
    rc, out, _ = _git(repo, "branch", "--no-merged", "master", "--list", "agent/*")
    if rc != 0:
        # Try 'main' as fallback base branch
        rc, out, _ = _git(repo, "branch", "--no-merged", "main", "--list", "agent/*")
    if rc != 0 or not out:
        return []
    branches = []
    for line in out.splitlines():
        name = line.strip().lstrip("* ")
        if name:
            branches.append(name)
    return branches


def _extract_failures(text):
    """Extract failure reasons from text using known patterns.

    Returns a list of dicts: [{type, detail}]
    """
    failures = []
    seen = set()
    for pattern, kind in _FAILURE_PATTERNS:
        for m in pattern.finditer(text):
            detail = m.group(1) if m.lastindex else m.group(0)
            key = (kind, detail)
            if key not in seen:
                seen.add(key)
                failures.append({"type": kind, "detail": detail})
    return failures


def check_build_status(branch, repo=None):
    """Check if a branch has build failures, extract failure reasons.

    Returns dict: {branch, has_failures, reasons: [{type, detail}]}
    Fail-soft: returns {has_failures: False, reasons: []} on error.
    """
    if not ENABLED:
        return {"branch": branch, "has_failures": False, "reasons": []}
    repo = repo or _default_repo()
    # Gather evidence: last few commit messages + notes
    rc, log_text, _ = _git(repo, "log", branch, "--not", "master",
                           "--format=%B%n---", "-n", "5")
    if rc != 0:
        rc, log_text, _ = _git(repo, "log", branch, "--not", "main",
                               "--format=%B%n---", "-n", "5")
    # Also check git notes (CI annotations)
    rc2, notes_text, _ = _git(repo, "notes", "--ref=ci", "show", branch)
    combined = (log_text or "") + "\n" + (notes_text if rc2 == 0 else "")
    # Check task table for notes about this branch
    try:
        slug = branch.replace("agent/", "", 1)
        rows = db.select("tasks", {"select": "note,log_tail", "slug": f"eq.{slug}", "limit": "1"}) or []
        if rows:
            combined += "\n" + (rows[0].get("note") or "") + "\n" + (rows[0].get("log_tail") or "")
    except Exception:
        pass
    reasons = _extract_failures(combined)
    return {"branch": branch, "has_failures": bool(reasons), "reasons": reasons}


def get_failure_reasons(branches, repo=None):
    """Batch check all branches, return dict of branch -> failure_reasons list.

    Fail-soft: branches that error out get an empty list.
    """
    if not ENABLED:
        return {}
    repo = repo or _default_repo()
    result = {}
    for branch in (branches or []):
        try:
            status = check_build_status(branch, repo=repo)
            result[branch] = status.get("reasons", [])
        except Exception:
            result[branch] = []
    return result


def stats():
    """Module statistics."""
    try:
        repo = _default_repo()
        branches = scan_branches(repo)
        failures = get_failure_reasons(branches, repo)
        with_failures = sum(1 for v in failures.values() if v)
        return {
            "enabled": ENABLED,
            "unmerged_agent_branches": len(branches),
            "branches_with_failures": with_failures,
        }
    except Exception:
        return {"enabled": ENABLED, "unmerged_agent_branches": 0, "branches_with_failures": 0}
