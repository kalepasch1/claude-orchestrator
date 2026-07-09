#!/usr/bin/env python3
"""sentinel.py — the fleet's self-healing layer. Runs every ~2 min (launchd job on Mac 1,
runner periodic on every machine) and auto-remediates the failure modes that previously
required a human session, so the orchestrator never sits broken:

  1. DB outage       -> detects Supabase down; after 3 consecutive misses switches to OFFLINE
                        MODE: runs the DB-independent git deploy sweep (rate-limited) so
                        deployments continue; on recovery re-ingests intake drops and
                        re-asserts the fleet_config baseline.
  2. Checkout drift  -> main repo parked on an agent branch (aborted rebase etc.): stash any
                        dirt, return to the canonical base branch, ff-pull. (Root cause of the
                        2026-07-08/09 stale-code incidents.)
  3. Runner health   -> 0 runners: kickstart the launchd service. >1 runner/keepalive:
                        kill the orphans (SIGKILL; supervisor-lock holder wins).
  4. RAM clamp       -> free RAM under floor+2GB with a big local model loaded: unload the
                        largest Ollama model (the codestral/qwen 'limit=1' clamp).
  5. Stale code      -> origin/base ahead of local: ff-pull; runner booted on an older commit:
                        request cooperative restart; request ignored >45 min: cycle the runner
                        process (keepalive respawns it on current code).
  6. Train silence   -> DB up but no merge_train output for 30+ min: fire one train run.

Every action is journaled to .runtime/sentinel.log + .runtime/sentinel_state.json.
Fail-soft everywhere: a sentinel bug must never take the fleet down with it.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)
RUNTIME = os.path.join(REPO, ".runtime")
STATE_PATH = os.path.join(RUNTIME, "sentinel_state.json")
LOG_PATH = os.path.join(RUNTIME, "sentinel.log")
BASE_BRANCH = os.environ.get("ORCH_BASE_BRANCH", "master")
SERVICE = os.environ.get("ORCH_LAUNCHD_SERVICE", "com.claudeorchestrator.runner")
DB_DOWN_THRESHOLD = int(os.environ.get("SENTINEL_DB_DOWN_THRESHOLD", "3"))
SWEEP_MIN_INTERVAL_S = int(os.environ.get("SENTINEL_SWEEP_INTERVAL_S", "2700"))
TRAIN_STALE_S = int(os.environ.get("SENTINEL_TRAIN_STALE_S", "1800"))
RESTART_STALE_S = int(os.environ.get("SENTINEL_RESTART_STALE_S", "2700"))
RAM_GUARD_FREE_GB = float(os.environ.get("SENTINEL_RAM_GUARD_FREE_GB", "6"))


def log(action, detail=""):
    line = f"{datetime.datetime.utcnow().isoformat()}Z sentinel {action} {str(detail)[:240]}"
    print(line, flush=True)
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {}


def save_state(st):
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        json.dump(st, open(STATE_PATH, "w"), indent=1)
    except OSError:
        pass


def sh(*args, timeout=60, cwd=REPO):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=timeout)


def git(*args, timeout=120):
    return sh("git", *args, timeout=timeout)


# ── 1. DB probe + offline mode ────────────────────────────────────────────────

def db_up():
    try:
        os.environ.setdefault("ORCH_SUPABASE_TIMEOUT", "15")
        import db
        db.select("tasks", {"select": "id", "limit": "1"})
        return True
    except Exception as e:
        log("db-down", str(e)[:80])
        return False


def offline_deploy_sweep(st):
    last = float(st.get("last_sweep_t", 0))
    if time.time() - last < SWEEP_MIN_INTERVAL_S:
        return
    st["last_sweep_t"] = time.time()
    script = os.path.join(REPO, "scripts", "git_deploy_sweep.py")
    if not os.path.isfile(script):
        return
    log("offline-sweep", "DB down — running DB-independent deploy sweep in background")
    subprocess.Popen([sys.executable, script],
                     stdout=open(os.path.join(RUNTIME, "git_deploy_sweep.out"), "a"),
                     stderr=subprocess.STDOUT, cwd=REPO)


def on_db_recovery():
    log("db-recovered", "re-ingesting intake + re-asserting fleet_config baseline")
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "intake_watcher.py")],
                       capture_output=True, timeout=300, cwd=HERE)
    except Exception as e:
        log("intake-ingest-failed", e)
    try:
        baseline = os.path.join(REPO, "scripts", "fleet_config_baseline.json")
        if os.path.isfile(baseline):
            import db
            for k, v in json.load(open(baseline)).items():
                db.insert("fleet_config", {"key": k, "value": str(v)}, upsert=True)
            log("fleet-config-asserted", "baseline keys pushed")
    except Exception as e:
        log("fleet-config-failed", e)


# ── 2. checkout drift guard ───────────────────────────────────────────────────

def checkout_guard():
    gitdir = os.path.join(REPO, ".git")
    if any(os.path.isdir(os.path.join(gitdir, d)) for d in ("rebase-merge", "rebase-apply")):
        return  # a rebase is genuinely in progress somewhere — do not interfere
    branch = git("branch", "--show-current").stdout.strip()
    if branch == BASE_BRANCH:
        git("pull", "--ff-only", "origin", BASE_BRANCH, timeout=180)
        return
    log("checkout-drift", f"main checkout on '{branch}' — restoring {BASE_BRANCH}")
    if git("status", "--porcelain").stdout.strip():
        git("stash", "push", "-u", "-m", f"sentinel-drift-{branch}-{int(time.time())}")
    r = git("checkout", BASE_BRANCH)
    if r.returncode != 0:
        log("checkout-failed", r.stderr[-120:])
        return
    git("pull", "--ff-only", "origin", BASE_BRANCH, timeout=180)
    log("checkout-restored", BASE_BRANCH)


# ── 3. runner singleton guard ─────────────────────────────────────────────────

def _pids(pattern):
    out = sh("pgrep", "-f", pattern).stdout.split()
    me = str(os.getpid())
    return [p for p in out if p != me]


def runner_guard(st):
    runners = _pids("MacOS/Python runner.py") + _pids("python3 runner.py")
    keepalives = _pids("keepalive.sh")
    if not runners:
        misses = int(st.get("runner_misses", 0)) + 1
        st["runner_misses"] = misses
        if misses >= 2:  # ~4 min without a runner
            log("runner-missing", f"kickstarting {SERVICE}")
            sh("launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{SERVICE}")
            st["runner_misses"] = 0
        return
    st["runner_misses"] = 0
    if len(runners) > 1:
        # keep the newest (freshest code), kill the rest
        by_start = []
        for p in runners:
            et = sh("ps", "-o", "etimes=", "-p", p).stdout.strip()
            try:
                by_start.append((int(et), p))
            except ValueError:
                continue
        by_start.sort()
        for _, p in by_start[1:]:
            log("extra-runner-killed", p)
            sh("kill", "-9", p)
    if len(keepalives) > 1:
        lock_pid = ""
        try:
            lock_pid = open(os.path.join(RUNTIME, "keepalive.lock", "pid")).read().strip()
        except OSError:
            pass
        for p in keepalives:
            if lock_pid and p != lock_pid:
                log("extra-keepalive-killed", p)
                sh("kill", "-9", p)


# ── 4. RAM clamp guard ────────────────────────────────────────────────────────

def ram_guard():
    try:
        vm = sh("vm_stat").stdout
        m = re.search(r"Pages free:\s+(\d+)", vm)
        free_gb = int(m.group(1)) * 16384 / 1e9 if m else 99
        if free_gb >= RAM_GUARD_FREE_GB:
            return
        ps = sh("ollama", "ps").stdout.splitlines()[1:]
        models = []
        for line in ps:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    models.append((float(parts[2]), parts[0]))
                except ValueError:
                    continue
        models.sort(reverse=True)
        if models and models[0][0] >= 8:
            log("ram-clamp", f"free {free_gb:.1f}GB — unloading {models[0][1]} ({models[0][0]}GB)")
            sh("ollama", "stop", models[0][1], timeout=90)
    except Exception as e:
        log("ram-guard-error", e)


# ── 5. stale code / restart guard ─────────────────────────────────────────────

def stale_code_guard():
    req = os.path.join(HERE, ".restart_requested")
    boot = ""
    for p in (os.path.join(REPO, ".runner_boot_commit"), os.path.join(HERE, ".runner_boot_commit")):
        try:
            boot = open(p).read().strip()
            break
        except OSError:
            continue
    head = git("rev-parse", "HEAD").stdout.strip()
    if boot and head and boot != head:
        if not os.path.exists(req):
            with open(req, "w") as f:
                f.write(f"reason=sentinel: runner boot {boot[:9]} != HEAD {head[:9]}\n")
            log("restart-requested", f"{boot[:9]} -> {head[:9]}")
        elif time.time() - os.path.getmtime(req) > RESTART_STALE_S:
            runners = _pids("MacOS/Python runner.py") + _pids("python3 runner.py")
            for p in runners:
                log("runner-cycled", f"cooperative restart ignored {RESTART_STALE_S}s; killing {p}")
                sh("kill", p)


# ── 6. merge-train recency (DB up only) ──────────────────────────────────────

def train_guard():
    marker = os.path.join(RUNTIME, "merge_train_pressure.json")
    try:
        age = time.time() - os.path.getmtime(marker)
    except OSError:
        age = 1e9
    if age > TRAIN_STALE_S:
        log("train-stale", f"{int(age)}s since last train pressure write — firing train_run")
        subprocess.Popen([sys.executable, os.path.join(HERE, "merge_train.py")],
                         stdout=open(os.path.join(RUNTIME, "sentinel_train.out"), "a"),
                         stderr=subprocess.STDOUT, cwd=HERE)


def main():
    st = load_state()
    up = db_up()
    was_down = int(st.get("db_misses", 0)) >= DB_DOWN_THRESHOLD
    st["db_misses"] = 0 if up else int(st.get("db_misses", 0)) + 1
    try:
        checkout_guard()
    except Exception as e:
        log("checkout-guard-error", e)
    try:
        runner_guard(st)
    except Exception as e:
        log("runner-guard-error", e)
    try:
        ram_guard()
    except Exception as e:
        log("ram-guard-error", e)
    try:
        stale_code_guard()
    except Exception as e:
        log("stale-code-error", e)
    if up:
        if was_down:
            try:
                on_db_recovery()
            except Exception as e:
                log("recovery-error", e)
        try:
            train_guard()
        except Exception as e:
            log("train-guard-error", e)
    elif int(st.get("db_misses", 0)) >= DB_DOWN_THRESHOLD:
        try:
            offline_deploy_sweep(st)
        except Exception as e:
            log("sweep-error", e)
    st["last_run"] = datetime.datetime.utcnow().isoformat() + "Z"
    st["db_up"] = up
    save_state(st)
    log("ok", f"db={'up' if up else 'DOWN'} misses={st['db_misses']}")


if __name__ == "__main__":
    main()
