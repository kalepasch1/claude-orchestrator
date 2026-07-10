#!/usr/bin/env python3
"""Offline-capable resilience mesh for the orchestrator.

This process is intentionally DB-independent by default. When Supabase is down it
keeps the local fleet useful: records the outage, checks supervisor health,
records vendor availability, prewarms repos, and spools DB-required work for a
recovery sprint. When the DB comes back, db_recovery_sprint replays the normal
queue/janitor/merge/release path.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from typing import Any


RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(RUNNER_DIR)
RUNTIME_HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.join(REPO_ROOT, ".runtime"))
STATE_PATH = os.path.join(RUNTIME_HOME, "resilience_mesh.json")
SPOOL_DIR = os.path.join(RUNTIME_HOME, "offline_spool")
SPOOL_PATH = os.path.join(SPOOL_DIR, "resilience_actions.jsonl")
DB_HEALTH_PATH = os.path.join(RUNTIME_HOME, "db_health.json")
RUNNER_LOCK = os.path.join(RUNTIME_HOME, "runner.lock")
SWEEP_SCRIPT = os.path.join(REPO_ROOT, "scripts", "git_deploy_sweep.py")


def _now() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _truthy(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _load_runner_env() -> None:
    env_path = os.path.join(RUNNER_DIR, ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            raw_lines = f.readlines()
    except OSError:
        return
    pairs = []
    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#")[0].strip().strip('"').strip("'")
        pairs.append((key, value))
    anthropic_pairs = []
    for key, value in pairs:
        if key == "ANTHROPIC_API_KEY" or key.startswith("ANTHROPIC_API_KEY_"):
            anthropic_pairs.append((key, value))
            continue
        os.environ.setdefault(key, value)
    subscription_mode = os.environ.get("ORCH_USE_SUBSCRIPTION", "true").lower() == "true"
    api_billing = os.environ.get("ORCH_ALLOW_API_BILLING", "false").lower() == "true"
    if subscription_mode and not api_billing:
        return
    for key, value in anthropic_pairs:
        os.environ.setdefault(key, value)


_load_runner_env()


def _read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _append_spool(action: dict[str, Any]) -> None:
    os.makedirs(SPOOL_DIR, exist_ok=True)
    row = {"at": _now(), **action}
    with open(SPOOL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _age_seconds(iso: str | None) -> float:
    if not iso:
        return 10**9
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return max(0.0, time.time() - dt.timestamp())
    except Exception:
        return 10**9


def _db_health(max_age_s: int = 120) -> dict[str, Any]:
    if _truthy("ORCH_RESILIENCE_ASSUME_DB_DOWN"):
        return {"ok": False, "status": "down", "checked_at": _now(),
                "error": "forced by ORCH_RESILIENCE_ASSUME_DB_DOWN",
                "source": "resilience_mesh"}
    cached = _read_json(DB_HEALTH_PATH, {})
    if isinstance(cached, dict) and cached.get("checked_at") and _age_seconds(cached.get("checked_at")) <= max_age_s:
        return cached

    # Keep the outage detector fast. db.py reads this at import time.
    os.environ.setdefault("ORCH_SUPABASE_TIMEOUT", os.environ.get("ORCH_RESILIENCE_DB_TIMEOUT", "12"))
    try:
        import db_recovery_sprint

        probe = db_recovery_sprint._probe_db()
    except Exception as e:
        probe = {"ok": False, "status": "down", "checked_at": _now(), "error": str(e)[:240]}
    probe = {**probe, "source": "resilience_mesh"}
    _write_json(DB_HEALTH_PATH, probe)
    return probe


def _load_git_sweep_repos() -> dict[str, tuple[str, str, str | None]]:
    if not os.path.isfile(SWEEP_SCRIPT):
        return {}
    try:
        spec = importlib.util.spec_from_file_location("git_deploy_sweep", SWEEP_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return dict(getattr(mod, "REPOS", {}) or {})
    except Exception:
        return {}


def _discover_repos() -> list[dict[str, Any]]:
    repos: dict[str, dict[str, Any]] = {}
    for name, value in _load_git_sweep_repos().items():
        try:
            path, base, gate = value
        except Exception:
            continue
        if os.path.isdir(path):
            repos[name] = {"name": name, "path": path, "base": base, "gate": gate}

    extra_raw = os.environ.get("ORCH_RESILIENCE_REPOS_JSON", "")
    if extra_raw.strip():
        try:
            for row in json.loads(extra_raw):
                name = row.get("name") or os.path.basename(row.get("path", "repo"))
                path = row.get("path")
                if path and os.path.isdir(path):
                    repos[name] = {**row, "name": name, "path": path}
        except Exception:
            pass
    return sorted(repos.values(), key=lambda r: r.get("name", ""))


def _read_lock_pid() -> int | None:
    try:
        pid = int(open(RUNNER_LOCK, encoding="utf-8").read().strip())
        os.kill(pid, 0)
        return pid
    except Exception:
        return None


def _process_rows() -> list[dict[str, Any]]:
    try:
        res = subprocess.run(["ps", "-axo", "pid,ppid,command"], text=True,
                             capture_output=True, timeout=10)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in (res.stdout or "").splitlines()[1:]:
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "command": parts[2]})
        except Exception:
            continue
    return rows


def _supervisor_sanity() -> dict[str, Any]:
    rows = _process_rows()
    lock_pid = _read_lock_pid()
    runners = [r for r in rows if "runner.py" in r["command"]]
    keepalives = [r for r in rows if "keepalive.sh" in r["command"]]
    claude_runner = [r for r in rows if "ClaudeRunner.app" in r["command"]]
    duplicate_runner_pids = [r["pid"] for r in runners if lock_pid and r["pid"] != lock_pid]
    duplicate_keepalive_pids = [
        r["pid"] for r in keepalives
        if r["ppid"] == 1 and "./keepalive.sh" in r["command"]
    ]
    killed: list[int] = []
    if _truthy("ORCH_RESILIENCE_KILL_DUPLICATES", True):
        for pid in duplicate_runner_pids + duplicate_keepalive_pids:
            if pid == os.getpid():
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append(pid)
            except Exception:
                pass
    return {
        "lock_pid": lock_pid,
        "runner_pids": [r["pid"] for r in runners],
        "keepalive_pids": [r["pid"] for r in keepalives],
        "claude_runner_pids": [r["pid"] for r in claude_runner],
        "duplicate_runner_pids": duplicate_runner_pids,
        "duplicate_keepalive_pids": duplicate_keepalive_pids,
        "killed": killed,
    }


def _vendor_status() -> dict[str, Any]:
    # Do not import agentic_coders/route_evidence here: their normal path may
    # read DB-backed controls (for purchased-credit mode), which is exactly what
    # this mesh must avoid during Supabase outages.
    providers = ["claude"]
    disabled = []
    if os.environ.get("OPENAI_API_KEY", "").strip():
        providers.append("openai")
    else:
        disabled.append({"provider": "openai", "reason": "OPENAI_API_KEY not configured"})
    if (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip():
        providers.append("google")
    else:
        disabled.append({"provider": "google", "reason": "GOOGLE_API_KEY/GEMINI_API_KEY not configured"})
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        providers.append("deepseek")
    else:
        disabled.append({"provider": "deepseek", "reason": "DEEPSEEK_API_KEY not configured"})

    local_up = bool(os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_MODEL"))
    if not local_up:
        for host in ("http://127.0.0.1:11434", "http://localhost:11434"):
            try:
                if subprocess.run(["curl", "-sf", host + "/api/tags"],
                                  text=True, capture_output=True, timeout=2).returncode == 0:
                    local_up = True
                    break
            except Exception:
                pass
    if local_up:
        providers.append("local")
    else:
        disabled.append({"provider": "local", "reason": "OLLAMA_HOST/model not configured and local Ollama did not answer quickly"})

    paid_env = _truthy("ORCH_USE_PAID_AGENTIC_CREDITS") or _truthy("ORCH_ALLOW_API_BILLING")
    coders = ["claude"]
    if local_up:
        coders.append("ollama")
    if paid_env:
        if "deepseek" in providers:
            coders.append("deepseek")
        if "google" in providers:
            coders.append("gemini")
        if "openai" in providers:
            coders.extend(["gpt-mini", "gpt"])
    return {
        "available_providers": sorted(set(providers)),
        "agentic_coders": coders,
        "disabled_providers": disabled,
        "credit_mode_source": "env-only; DB controls skipped in resilience mesh",
    }


def _prewarm_repos(repos: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    if not _truthy("ORCH_RESILIENCE_PREWARM", False):
        return {"ok": True, "skipped": "disabled"}
    cap = max(0, int(os.environ.get("ORCH_RESILIENCE_PREWARM_LIMIT", "2")))
    if cap <= 0 or not repos:
        return {"ok": True, "skipped": "no-repos"}
    cursor = int(state.get("prewarm_cursor", 0) or 0) % len(repos)
    selected = [repos[(cursor + i) % len(repos)] for i in range(min(cap, len(repos)))]
    results = []
    try:
        import dependency_prewarm
    except Exception as e:
        return {"ok": False, "error": str(e)[:240], "selected": [r["name"] for r in selected]}
    timeout = int(os.environ.get("ORCH_RESILIENCE_PREWARM_TIMEOUT", "180"))
    for repo in selected:
        started = time.time()
        try:
            res = dependency_prewarm.ensure_all(repo["path"], reason="resilience-mesh", timeout=timeout)
        except Exception as e:
            res = {"ok": False, "error": str(e)[:400]}
        results.append({"repo": repo["name"], "seconds": round(time.time() - started, 1), **(res or {})})
    state["prewarm_cursor"] = (cursor + len(selected)) % max(1, len(repos))
    return {"ok": all(bool(r.get("ok")) for r in results), "results": results}


def _deploy_sweep_plan(repos: list[dict[str, Any]]) -> dict[str, Any]:
    names = [r["name"] for r in repos]
    if not names:
        return {"enabled": False, "reason": "no repos discovered", "repos": []}
    if not _truthy("ORCH_RESILIENCE_DEPLOY_SWEEP", False):
        _append_spool({
            "type": "deploy_sweep_ready",
            "reason": "enable ORCH_RESILIENCE_DEPLOY_SWEEP=true to run gated branch push sweep",
            "repos": names,
        })
        return {"enabled": False, "reason": "push sweep disabled", "repos": names}
    env = os.environ.copy()
    env.setdefault("SWEEP_PER_REPO_CAP", os.environ.get("ORCH_RESILIENCE_SWEEP_PER_REPO_CAP", "2"))
    env.setdefault("SWEEP_GATE_TIMEOUT", os.environ.get("ORCH_RESILIENCE_SWEEP_GATE_TIMEOUT", "900"))
    started = time.time()
    try:
        res = subprocess.run([sys.executable, SWEEP_SCRIPT, *names], cwd=REPO_ROOT, env=env,
                             text=True, capture_output=True,
                             timeout=int(os.environ.get("ORCH_RESILIENCE_SWEEP_TIMEOUT", "1800")))
        return {
            "enabled": True,
            "ok": res.returncode == 0,
            "code": res.returncode,
            "seconds": round(time.time() - started, 1),
            "stdout": (res.stdout or "")[-1600:],
            "stderr": (res.stderr or "")[-1600:],
        }
    except Exception as e:
        return {"enabled": True, "ok": False, "seconds": round(time.time() - started, 1),
                "error": str(e)[:400]}


def _spool_db_required(db_health: dict[str, Any]) -> None:
    _append_spool({
        "type": "db_recovery_required",
        "db_status": db_health.get("status"),
        "db_error": db_health.get("error"),
        "actions": [
            "run intake_watcher",
            "run queue_janitor",
            "run task_dedup",
            "run merge_train",
            "run release_train",
            "run deploy_verify",
            "run autopilot",
        ],
    })


def _spool_depth() -> int:
    try:
        with open(SPOOL_PATH, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _run_recovery_sprint(force: bool = False) -> dict[str, Any]:
    if not _truthy("ORCH_RESILIENCE_SYNC_RECOVERY", False):
        log_base = os.path.join(RUNTIME_HOME, "logs", "db-recovery-sprint")
        os.makedirs(os.path.dirname(log_base), exist_ok=True)
        cmd = [sys.executable, os.path.join(RUNNER_DIR, "db_recovery_sprint.py")]
        if force:
            cmd.append("--force")
        try:
            with open(log_base + ".log", "a", encoding="utf-8") as out, open(log_base + ".err", "a", encoding="utf-8") as err:
                proc = subprocess.Popen(cmd, cwd=RUNNER_DIR, env=os.environ.copy(), stdout=out, stderr=err)
            return {"ran": False, "launched": True, "pid": proc.pid, "mode": "async"}
        except Exception as e:
            return {"ran": False, "launched": False, "error": str(e)[:400]}
    try:
        import db_recovery_sprint

        return db_recovery_sprint.run(force=force)
    except Exception as e:
        return {"ran": False, "error": str(e)[:400]}


def run() -> dict[str, Any]:
    state = _read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    db_health = _db_health()
    repos = _discover_repos()
    supervisor = _supervisor_sanity()
    vendors = _vendor_status()
    actions: dict[str, Any] = {}

    if not db_health.get("ok"):
        _spool_db_required(db_health)
        actions["prewarm"] = _prewarm_repos(repos, state)
        actions["deploy_sweep"] = _deploy_sweep_plan(repos)
        mode = "offline-continuity"
    else:
        recovered = state.get("last_mode") == "offline-continuity"
        actions["recovery_sprint"] = _run_recovery_sprint(force=recovered)
        mode = "online-drain"

    out = {
        "updated_at": _now(),
        "mode": mode,
        "db": db_health,
        "spool_depth": _spool_depth(),
        "repos": [{"name": r["name"], "path": r["path"], "base": r.get("base")} for r in repos],
        "supervisor": supervisor,
        "vendors": vendors,
        "actions": actions,
    }
    state.update(out)
    state["last_mode"] = mode
    _write_json(STATE_PATH, state)
    print(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    run()
