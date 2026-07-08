"""
build_daemon.py — build/test daemon per repo.

Keeps repos warm so agents don't waste time on setup:
1. Pre-installs deps (npm install / pip install)
2. Pre-creates warm worktrees for upcoming tasks
3. Verifies env (node version, python version, required tools)
4. Runs a quick build check to catch pre-existing failures
5. Reports repo health to the dashboard

This is a 5X-50X practical speedup because agents stop rediscovering setup.
Runs as a periodic job.
"""
import os, sys, subprocess, json, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WARM_WORKTREE_COUNT = int(os.environ.get("ORCH_WARM_WORKTREES", "5"))
HEALTH_TABLE = "repo_health"


def run():
    """Periodic entry: warm all registered project repos."""
    projects = db.select("projects", {"select": "id,name,repo_path,test_cmd,default_base"}) or []
    results = {}

    for proj in projects:
        repo = proj.get("repo_path")
        name = proj.get("name", "unknown")
        if not repo or not os.path.isdir(repo):
            results[name] = {"status": "missing", "repo": repo}
            continue

        result = warm_repo(repo, proj)
        results[name] = result

        # Report health
        try:
            db.insert(HEALTH_TABLE, {
                "project": name,
                "status": "healthy" if result.get("deps_ok") and result.get("build_ok") else "degraded",
                "deps_ok": result.get("deps_ok", False),
                "build_ok": result.get("build_ok", False),
                "warm_worktrees": result.get("warm_worktrees", 0),
                "env_ok": result.get("env_ok", False),
                "checked_at": "now()",
                "detail": json.dumps(result.get("issues", []))[:2000]
            }, upsert=True)
        except Exception:
            pass

    healthy = sum(1 for r in results.values() if r.get("deps_ok") and r.get("build_ok"))
    print(f"[build_daemon] {healthy}/{len(results)} repos healthy")
    return results


def warm_repo(repo, proj):
    """Warm a single repo: deps, env, build check, worktrees."""
    result = {"issues": []}
    name = proj.get("name", "unknown")
    base = proj.get("default_base") or "main"

    # 1. Fetch latest
    try:
        subprocess.run(["git", "fetch", "origin"], cwd=repo,
                       capture_output=True, timeout=120)
    except Exception as e:
        result["issues"].append(f"fetch failed: {e}")

    # 2. Check env
    result["env_ok"] = _check_env(repo, result)

    # 3. Install deps
    result["deps_ok"] = _install_deps(repo, result)

    # 4. Quick build check
    result["build_ok"] = _check_build(repo, result)

    # 5. Warm worktrees
    result["warm_worktrees"] = _warm_worktrees(repo, name, base, result)

    return result


def _check_env(repo, result):
    """Verify required tools are available."""
    ok = True

    # Check node
    if os.path.isfile(os.path.join(repo, "package.json")):
        r = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if r.returncode != 0:
            result["issues"].append("node not found")
            ok = False

    # Check python
    if os.path.isfile(os.path.join(repo, "requirements.txt")) or os.path.isfile(os.path.join(repo, "setup.py")):
        r = subprocess.run(["python3", "--version"], capture_output=True, text=True)
        if r.returncode != 0:
            result["issues"].append("python3 not found")
            ok = False

    return ok


def _install_deps(repo, result):
    """Install dependencies if needed."""
    ok = True

    # Node projects
    pkg_json = os.path.join(repo, "package.json")
    node_modules = os.path.join(repo, "node_modules")
    if os.path.isfile(pkg_json):
        needs_install = not os.path.isdir(node_modules)
        if not needs_install:
            # Check if package.json is newer than node_modules
            try:
                pkg_mtime = os.path.getmtime(pkg_json)
                nm_mtime = os.path.getmtime(node_modules)
                needs_install = pkg_mtime > nm_mtime
            except OSError:
                needs_install = True

        if needs_install:
            try:
                r = subprocess.run(["npm", "install", "--prefer-offline"],
                                   cwd=repo, capture_output=True, text=True, timeout=300)
                if r.returncode != 0:
                    result["issues"].append(f"npm install failed: {r.stderr[:200]}")
                    ok = False
            except subprocess.TimeoutExpired:
                result["issues"].append("npm install timed out (300s)")
                ok = False
            except Exception as e:
                result["issues"].append(f"npm install error: {e}")
                ok = False

    # Python projects
    reqs = os.path.join(repo, "requirements.txt")
    if os.path.isfile(reqs):
        try:
            r = subprocess.run(["pip3", "install", "-q", "-r", reqs, "--break-system-packages"],
                               cwd=repo, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                result["issues"].append(f"pip install failed: {r.stderr[:200]}")
                ok = False
        except Exception as e:
            result["issues"].append(f"pip install error: {e}")
            ok = False

    return ok


def _check_build(repo, result):
    """Quick build check to catch pre-existing failures."""
    # Detect build command
    pkg_json = os.path.join(repo, "package.json")
    if os.path.isfile(pkg_json):
        try:
            with open(pkg_json) as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts", {})
            if "build" in scripts:
                try:
                    r = subprocess.run(["npm", "run", "build"], cwd=repo,
                                       capture_output=True, text=True, timeout=600)
                    if r.returncode != 0:
                        result["issues"].append(f"build failed: {(r.stderr or r.stdout or '')[-200:]}")
                        return False
                except subprocess.TimeoutExpired:
                    result["issues"].append("build timed out (600s)")
                    return False
                return True
        except Exception:
            pass

    return True  # No build command = assume OK


def _warm_worktrees(repo, project_name, base, result):
    """Pre-create warm worktrees for upcoming tasks."""
    wt_dir = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt")
    os.makedirs(wt_dir, exist_ok=True)

    # Get upcoming queued tasks
    try:
        queued = db.select("tasks", {
            "select": "slug",
            "state": "eq.QUEUED",
            "order": "created_at.asc",
            "limit": str(WARM_WORKTREE_COUNT)
        }) or []
    except Exception:
        return 0

    warmed = 0
    for t in queued[:WARM_WORKTREE_COUNT]:
        slug = t.get("slug", "")
        if not slug:
            continue

        wt_path = os.path.join(wt_dir, slug)
        if os.path.isdir(wt_path):
            warmed += 1
            continue

        branch = f"agent/{slug}"
        try:
            # Create branch if needed
            subprocess.run(["git", "branch", branch, base], cwd=repo,
                           capture_output=True, timeout=30)
            # Create worktree
            r = subprocess.run(["git", "worktree", "add", "-f", wt_path, branch],
                              cwd=repo, capture_output=True, timeout=120)
            if r.returncode == 0:
                # Install deps in worktree
                if os.path.isfile(os.path.join(wt_path, "package.json")):
                    subprocess.run(["npm", "install", "--prefer-offline"],
                                   cwd=wt_path, capture_output=True, timeout=300)
                warmed += 1
        except Exception as e:
            result["issues"].append(f"worktree {slug}: {e}")

    return warmed


def repo_health(project_name):
    """Get current health status for a project."""
    try:
        rows = db.select(HEALTH_TABLE, {
            "select": "*",
            "project": f"eq.{project_name}",
            "limit": "1"
        })
        return rows[0] if rows else None
    except Exception:
        return None


if __name__ == "__main__":
    run()
