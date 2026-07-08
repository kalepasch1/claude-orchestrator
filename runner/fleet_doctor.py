#!/usr/bin/env python3
"""Health checks for a Mac runner joining the shared fleet."""
import argparse
import datetime
import json
import os
import platform
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "runner")
HOST = socket.gethostname()


def _claude_runner_app_dir():
    candidates = [
        os.environ.get("ORCH_CLAUDE_RUNNER_APP_DIR"),
        "/Applications/ClaudeRunner.app",
        os.path.expanduser("~/Applications/ClaudeRunner.app"),
    ]
    for cand in candidates:
        if cand and os.path.isdir(cand):
            return cand
    return candidates[1]


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception as e:
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": str(e)})()


def _fresh(ts, ttl=240):
    if not ts:
        return False
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() <= ttl
    except Exception:
        return False


def _check(results, name, ok, detail="", severity="error"):
    results.append({"name": name, "ok": bool(ok), "severity": severity, "detail": detail})


def run():
    results = []
    env_path = os.path.join(RUNNER, ".env")
    _check(results, "runner .env exists", os.path.exists(env_path), env_path)
    _check(results, "Supabase URL configured", bool(os.environ.get("SUPABASE_URL")), "SUPABASE_URL")
    _check(results, "Supabase service key configured", bool(os.environ.get("SUPABASE_SERVICE_KEY")),
           "SUPABASE_SERVICE_KEY")

    git = _run(["git", "rev-parse", "--show-toplevel"])
    _check(results, "git repo detected", git.returncode == 0, (git.stdout or git.stderr).strip())

    for table in ("runner_heartbeats", "fleet_config", "fleet_control"):
        try:
            db.select(table, {"select": "*", "limit": "1"})
            _check(results, f"{table} reachable", True)
        except Exception as e:
            _check(results, f"{table} reachable", False, str(e)[:300])

    try:
        rows = db.select("runner_heartbeats", {
            "select": "hostname,last_seen,active_tasks,runner_id",
            "order": "last_seen.desc",
            "limit": "50",
        }) or []
        host_rows = [r for r in rows if r.get("hostname") in (HOST, HOST.replace(".local", ""))]
        _check(results, "this host heartbeat fresh", any(_fresh(r.get("last_seen")) for r in host_rows),
               f"host={HOST}", severity="warn")
        live = [r.get("hostname") for r in rows if _fresh(r.get("last_seen"))]
        _check(results, "fleet has live runners", bool(live), ", ".join(live[:8]), severity="warn")
    except Exception as e:
        _check(results, "heartbeat query", False, str(e)[:300])

    try:
        cfg = db.select("fleet_config", {"select": "key,value", "key": "eq.ORCH_AUTO_PULL", "limit": "1"}) or []
        env_auto = os.environ.get("ORCH_AUTO_PULL", "").lower() in ("1", "true", "yes", "on")
        db_auto = bool(cfg and str(cfg[0].get("value")).lower() in ("1", "true", "yes", "on"))
        _check(results, "auto-pull enabled", env_auto or db_auto,
               "set via runner/.env or `python3 runner/fleetctl.py bootstrap-defaults`", severity="warn")
    except Exception as e:
        _check(results, "auto-pull check", False, str(e)[:300], severity="warn")

    if platform.system() == "Darwin":
        app_dir = _claude_runner_app_dir()
        app = os.path.join(app_dir, "Contents/MacOS/ClaudeRunner")
        compat = os.path.join(app_dir, "Contents/MacOS/run")
        _check(results, "ClaudeRunner.app installed", os.path.exists(app) and os.access(app, os.X_OK), app)
        _check(results, "ClaudeRunner run shim installed", os.path.exists(compat) and os.access(compat, os.X_OK),
               compat, severity="warn")
        lc = _run(["launchctl", "list", "com.claudeorchestrator.runner"])
        _check(results, "launchd runner loaded", lc.returncode == 0, (lc.stdout or lc.stderr).strip(),
               severity="warn")

    try:
        projects = db.select("projects", {"select": "name,repo_path", "limit": "5000"}) or []
        missing = [f"{p.get('name')}:{p.get('repo_path')}" for p in projects
                   if p.get("repo_path") and not os.path.isdir(p.get("repo_path"))]
        _check(results, "project repo paths reachable", not missing,
               "; ".join(missing[:10]) + (f"; +{len(missing)-10} more" if len(missing) > 10 else ""),
               severity="warn")
    except Exception as e:
        _check(results, "project repo path check", False, str(e)[:300], severity="warn")

    return {
        "host": HOST,
        "repo": ROOT,
        "ok": not any((not r["ok"] and r["severity"] == "error") for r in results),
        "checks": results,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true")
    args = ap.parse_args()
    out = run()
    if args.brief:
        for r in out["checks"]:
            status = "ok" if r["ok"] else r["severity"].upper()
            print(f"{status:5} {r['name']} {('- ' + r['detail']) if r.get('detail') else ''}")
    else:
        print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
