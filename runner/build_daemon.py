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
import build_slots     # this daemon runs REAL production builds; they need a slot
import db

WARM_WORKTREE_COUNT = int(os.environ.get("ORCH_WARM_WORKTREES", "5"))
HEALTH_TABLE = "repo_health"

#: Whether step 4 runs a FULL production build of each repo's working tree, every
#: 600s, for a health field. Default OFF, and the reason is not tuning -- it is that
#: the result has never had anywhere to go. Checked 2026-09-02 against the fleet DB:
#:
#:     select table_name from information_schema.tables
#:      where table_schema='public' and table_name ilike '%health%';
#:     -> runner_health, deploy_health, portfolio_health, v_project_health, ...
#:        and NO repo_health
#:
#: HEALTH_TABLE does not exist. Every db.insert() below has been raising into a bare
#: `except Exception: pass` since the daemon was written, and repo_health() -- the only
#: reader -- returns None for every project, always. Nothing else in the tree selects
#: from it (grep: three hits, all in this file plus an unrelated controls key).
#:
#: What that bought, per 600s cycle per project: one `npm run build` in the LIVE repo,
#: 600s timeout, measured here at 4.7 GB RSS. Because it runs in the working tree
#: rather than an overlay it also writes .nuxt/.output underneath whichever agent is
#: working in that repo. The medic's journal shows this same build orphaned and reaped
#: at 15:49Z and again at 17:23Z on the day this was written.
#:
#: The check it claims to perform -- "catch pre-existing failures" -- is done properly
#: three times over by gates whose verdicts ARE read: build_gate (exact commit, in a
#: disposable overlay), clean_clone_gate (pristine `git archive` export, real install)
#: and release_train's production proof. This one was the only one that could not be
#: read by anybody.
#:
#: Set ORCH_BUILD_DAEMON_BUILD_CHECK=true to restore it (it is slotted either way).
BUILD_CHECK = os.environ.get("ORCH_BUILD_DAEMON_BUILD_CHECK", "false").lower() in (
    "1", "true", "yes", "on")


def run():
    """Periodic entry: warm all registered project repos."""
    projects = db.select("projects", {"select": "id,name,repo_path,test_cmd,default_base"}) or []
    results = {}
    _sink_errors = []

    for proj in projects:
        repo = proj.get("repo_path")
        name = proj.get("name", "unknown")
        if not repo or not os.path.isdir(repo):
            results[name] = {"status": "missing", "repo": repo}
            continue

        result = warm_repo(repo, proj)
        results[name] = result

        # Report health. `build_ok is False` -- not falsy: None means the build check
        # did not run (see BUILD_CHECK), and a check that did not run is not a failure.
        _build_bad = result.get("build_ok") is False
        try:
            db.insert(HEALTH_TABLE, {
                "project": name,
                "status": "healthy" if result.get("deps_ok") and not _build_bad else "degraded",
                "deps_ok": result.get("deps_ok", False),
                "build_ok": result.get("build_ok", False),
                "warm_worktrees": result.get("warm_worktrees", 0),
                "env_ok": result.get("env_ok", False),
                "checked_at": "now()",
                "detail": json.dumps(result.get("issues", []))[:2000]
            }, upsert=True)
        except Exception as exc:
            # NOT `pass`. This insert has been failing for the life of the daemon
            # because HEALTH_TABLE does not exist in the fleet DB, and the bare except
            # is why nobody knew: the daemon printed "n/n repos healthy" every cycle
            # while writing nothing at all. One line per cycle is the whole fix.
            _sink_errors.append("%s: %s" % (name, str(exc)[:120]))

    healthy = sum(1 for r in results.values()
                  if r.get("deps_ok") and r.get("build_ok") is not False)
    if _sink_errors:
        print("[build_daemon] health sink unwritable (%d project(s)); first: %s"
              % (len(_sink_errors), _sink_errors[0]), flush=True)
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
    """Build the working tree, or None when no verdict was produced.

    None, not True. A skipped check that reports success is the exact shape
    stub_guard.py blocks in agent diffs ("fabricated_critical_return"), and the
    caller below now distinguishes "green" from "never ran".
    """
    if not BUILD_CHECK:
        result["build_checked"] = False
        return None
    # Detect build command
    pkg_json = os.path.join(repo, "package.json")
    if os.path.isfile(pkg_json):
        try:
            with open(pkg_json) as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts", {})
            if "build" in scripts:
                try:
                    # BOUND THE BUILD. This is a full production build, the same cost as
                    # the one build_gate runs, and it was outside the fleet's limiter.
                    # Measured on this host 2026-09-02: FOUR concurrent `nuxt build`s with
                    # ORCH_MAX_CONCURRENT_BUILDS=2, because only build_gate ever took a
                    # slot -- the others came from build_daemon (here) and the periodic
                    # clean-clone sweep. A limiter wired into one of N callers is not a
                    # limit; it is a comment. See build_slots.
                    with build_slots.hold("build_daemon %s" % os.path.basename(str(repo))):
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

    return None    # no package.json, or unreadable: no verdict, not a green one


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
