#!/usr/bin/env python3
"""consilium_tick.py — ONE scheduling pass for the expert subsystem; launchd owns the cadence.

WHY THIS SHAPE (2026-09-12). The expert loops (corps, docket, forecaster, commission, and the
new theory lab / paper drafter / opportunity scan / ambiguity miner) were scheduled inside
runner.py's periodic table, so they only ran while the whole coding fleet was up — and the
fleet had been down since a reboot. They also share the fleet's drain/lean/queue-depth gates,
which pause "self-play" the moment the coding backlog grows. Thinking about the law is not
self-play; it is the product.

So the Consilium gets its own cadence, in the same pattern as the fleet's other launchd jobs:
a launchd `StartInterval` fires this script every few minutes; it runs AT MOST ONE job that is
due (sequential — one model-heavy job at a time, so RAM and the subscription rate limit are
shared predictably), records the run, writes a heartbeat, and exits. No long-running process,
nothing to keep alive, nothing to restart. Guards that matter still apply: the kill switch,
each job's own single-instance lock, a per-job timeout, and the frontier token budget (jobs
degrade to local models when it is out). It never claims coding tasks, never touches a repo
checkout, never merges or deploys.

Usage:
    consilium_tick.py                   # run the next due job (launchd)
    consilium_tick.py --once <job> [args]   # run one named job now
    consilium_tick.py --status          # schedule + frontier budget
"""
from __future__ import annotations
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("NODE_ENV", None)

# Defaults the expert subsystem wants; a value already in the environment (launchd plist, shell)
# wins, and db._load_env's setdefault means runner/.env cannot override these once set here.
_DEFAULTS = {
    "ORCH_CONSILIUM_V2": "true",
    "ORCH_FRONTIER_ENABLED": "true",
    "OLLAMA_STRONG_MODEL": "qwen3.5:27b-mlx",
    "OLLAMA_MODEL": "llama3.1:8b",
    "ORCH_OLLAMA_NUM_CTX": "16384",
    "LEGAL_DOCKET_BATCH": "3",
    "ORCH_EXPERT_RESEARCH_PER_TICK": "2",
    "ORCH_NIGHT_RESEARCH_MULT": "2",
    "PUBCOM_BATCH": "4",
}
for _k, _v in _DEFAULTS.items():
    os.environ.setdefault(_k, _v)

import db  # noqa: E402  (loads runner/.env with setdefault)

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
SCHED = os.path.join(HOME, "consilium", "schedule.json")

#: name -> (script, args, interval_s, timeout_s). Order = priority when several are due.
JOBS = [
    ("legal_docket",     "legal_docket.py",         [os.environ["LEGAL_DOCKET_BATCH"]], 1200, 3000),
    ("publication_commission", "publication_commission.py", [os.environ["PUBCOM_BATCH"]], 1800, 2400),
    ("paper_drafter",    "paper_drafter.py",        [],        3600, 3000),
    ("expert_corps",     "expert_corps.py",         ["tick"],  3600, 2400),
    ("corpus_forecaster", "corpus_forecaster.py",   [],        3600, 1200),
    ("theory_lab",       "theory_lab.py",           [],        10800, 3000),
    ("ambiguity_miner",  "ambiguity_miner.py",      [],        21600, 3000),
    ("reg_opportunity_scan", "reg_opportunity_scan.py", [],    43200, 2400),
    # 2026-09-12 — event-driven card staleness, benchmark sourcing, corpus embedding refresh.
    ("card_freshness",   "card_freshness.py",       ["--apply"], 21600, 600),
    ("benchmark_ingest", "benchmark_ingest.py",     [],        43200, 1500),
    ("corpus_index",     "corpus_retrieval.py",     ["build"], 86400, 3000),
]


def _load():
    try:
        with open(SCHED) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    try:
        os.makedirs(os.path.dirname(SCHED), exist_ok=True)
        tmp = SCHED + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, SCHED)
    except Exception:
        pass


def _paused():
    try:
        import kill_switch
        return bool(kill_switch.is_paused(None))
    except Exception:
        return False


def _log(msg):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] consilium: {msg}", flush=True)


def run_job(name, script, args, timeout_s):
    cmd = [sys.executable, os.path.join(HERE, script)] + [str(a) for a in args]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout_s)
        tail = (proc.stdout or "").strip().splitlines()[-8:]
        err = (proc.stderr or "").strip().splitlines()[-3:]
        _log(f"{name} rc={proc.returncode} in {time.time() - t0:.0f}s" +
             ("\n    " + "\n    ".join(tail) if tail else "") +
             ("\n    stderr: " + " | ".join(err) if err and proc.returncode != 0 else ""))
        return {"rc": proc.returncode, "secs": round(time.time() - t0), "tail": tail[-3:]}
    except subprocess.TimeoutExpired:
        _log(f"{name} TIMEOUT after {timeout_s}s")
        return {"rc": -1, "secs": timeout_s, "tail": ["timeout"]}
    except Exception as e:
        _log(f"{name} failed to launch: {type(e).__name__}: {e}")
        return {"rc": -2, "secs": 0, "tail": [str(e)[:120]]}


def heartbeat(state):
    try:
        import frontier
        b = frontier.budget()
    except Exception:
        b = {}
    payload = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "home": HERE,
               "last_runs": {k: v for k, v in state.items() if isinstance(v, dict)},
               "frontier": {k: b.get(k) for k in ("hour_used", "day_used", "hour_cap", "day_cap",
                                                   "in_cooldown", "cooldown_reason", "calls_24h",
                                                   "codex_day_used", "codex_calls_24h")}}
    try:
        db.upsert("controls", {"key": "consilium_heartbeat", "value": json.dumps(payload, default=str)})
    except Exception:
        pass
    return payload


def tick():
    """Run at most one due job, then exit. launchd calls this on its own interval."""
    if _paused():
        _log("kill switch paused — nothing run")
        return None
    state = _load()
    job = next_due(state)
    if job:
        name, script, args, interval, timeout_s = job
        res = run_job(name, script, args, timeout_s)
        state[name] = {"at": time.time(), **res}
        _save(state)
        heartbeat(state)
        return name
    heartbeat(state)
    return None


def next_due(state, now=None):
    """The due job that is MOST overdue relative to its own interval. (2026-09-12: a fixed priority
    order let the 20-minute docket and the 30-minute commission take every slot — the theory lab,
    the corps tick, the forecaster and both scans had not run once in six hours. Never-run jobs
    sort first.)"""
    now = now or time.time()
    best, best_ratio = None, 0.0
    for job in JOBS:
        name, _script, _args, interval, _timeout = job
        last = float((state.get(name) or {}).get("at") or 0)
        if now - last < interval:
            continue
        ratio = float("inf") if not last else (now - last) / float(interval)
        if ratio > best_ratio:
            best, best_ratio = job, ratio
    return best


def status():
    state = _load()
    now = time.time()
    rows = []
    for name, script, args, interval, timeout_s in JOBS:
        st = state.get(name) or {}
        last = float(st.get("at") or 0)
        rows.append({"job": name, "interval_min": interval // 60,
                     "last_run": datetime.datetime.fromtimestamp(last).isoformat() if last else None,
                     "due_in_min": max(0, round((last + interval - now) / 60)) if last else 0,
                     "rc": st.get("rc"), "secs": st.get("secs")})
    try:
        import frontier
        fb = frontier.status()
    except Exception as e:
        fb = {"error": str(e)}
    return {"paused": _paused(), "jobs": rows, "frontier": fb}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        print(json.dumps(status(), indent=2, default=str))
    elif len(sys.argv) > 1 and sys.argv[1] == "--once" and len(sys.argv) > 2:
        want = sys.argv[2]
        for name, script, args, interval, timeout_s in JOBS:
            if name == want:
                res = run_job(name, script, (sys.argv[3:] or args), timeout_s)
                st = _load(); st[name] = {"at": time.time(), **res}; _save(st)
                print(json.dumps(res, default=str))
                break
        else:
            print(f"unknown job {want}; known: {[j[0] for j in JOBS]}")
    else:
        ran = tick()
        _log(f"tick done: ran {ran or 'nothing (no job due)'}")
