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
degrade to local models when it is out). Host resource admission applies before both scheduled
and manual runs; deferred jobs remain due with bounded retry backoff. It never claims coding
tasks, never touches a repo checkout, never merges or deploys.

Usage:
    consilium_tick.py                   # run the next due job (launchd)
    consilium_tick.py --once <job> [args]   # run one named job now
    consilium_tick.py --status          # schedule + frontier budget
"""
from __future__ import annotations
import datetime
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("NODE_ENV", None)

# Load the normal configuration before applying subsystem fallbacks. Shell/launchd values
# still win through db._load_env's setdefault; central runner/.env must win over these defaults.
import db  # noqa: E402  (loads runner/.env with setdefault)
from consilium_outcomes import classify_outcome  # noqa: E402

_DEFAULTS = {
    "ORCH_CONSILIUM_V2": "true",
    "ORCH_FRONTIER_ENABLED": "true",
    "OLLAMA_STRONG_MODEL": "qwen3.5:27b-mlx",
    "OLLAMA_MODEL": "llama3.1:8b",
    "ORCH_OLLAMA_NUM_CTX": "4096",
    "LEGAL_DOCKET_BATCH": "3",
    "ORCH_EXPERT_RESEARCH_PER_TICK": "2",
    "ORCH_NIGHT_RESEARCH_MULT": "2",
    "PUBCOM_BATCH": "4",
}
for _k, _v in _DEFAULTS.items():
    os.environ.setdefault(_k, _v)

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
    # 2026-09-21 — commission-accepted, citation-verified cards -> the law app's advisory intel.
    ("consilium_export", "consilium_export.py",     ["--apply"], 3600, 600),
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


def _reason_code(reason, fallback):
    """Receipts and telemetry carry resource codes, never free-form child content."""
    return reason if isinstance(reason, str) and re.fullmatch(r"[a-z_]{1,80}", reason) else fallback


def _finite_number(value, default=0):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else default
    except (TypeError, ValueError):
        return default


def _retry_delay(attempts):
    base = min(3600, max(60, _finite_number(os.environ.get("ORCH_CONSILIUM_CAPACITY_RETRY_SECONDS"), 600)))
    return min(3600, base * 2 ** min(6, max(0, attempts - 1)))


def _capacity_receipt(path):
    """Only a bounded, per-child capacity signal; never job output or request content."""
    try:
        with open(path, "rb") as f:
            raw = f.read(4097)
        if len(raw) > 4096:
            raise ValueError("oversized receipt")
        receipt = json.loads(raw)
        if not isinstance(receipt, dict):
            raise ValueError("invalid receipt")
        if receipt.get("deferred") is False:
            return None
        reason = receipt.get("reason")
        if receipt.get("deferred") is not True:
            raise ValueError("invalid receipt")
        return _reason_code(reason, "local_capacity_receipt_invalid")
    except (OSError, ValueError, TypeError):
        return "local_capacity_receipt_invalid"


def run_job(name, script, args, timeout_s):
    # Gate the host, not the strong local model: a healthy job may use frontier/cloud.
    # Per-model admission belongs to the model gateway at the time of the actual call.
    try:
        from local_model_slots import host_admission_status
        admission = host_admission_status()
    except Exception:
        admission = {"admitted": False, "reason": "host_telemetry_unavailable"}
    if not isinstance(admission, dict) or admission.get("admitted") is not True:
        reason = admission.get("reason") if isinstance(admission, dict) else None
        reason = _reason_code(reason, "host_telemetry_unavailable")
        _log(f"{name} deferred: {reason}; remains due")
        return {"status": "deferred", "deferred": True, "reason": reason,
                "rc": None, "secs": 0, "tail": []}
    cmd = [sys.executable, os.path.join(HERE, script)] + [str(a) for a in args]
    t0 = time.time()
    try:
        # Some expert callers swallow a denied local fallback and exit zero. A private
        # receipt preserves that deferral without confusing it with a successful job.
        with tempfile.TemporaryDirectory(prefix="consilium-admission-") as receipt_dir:
            fd, receipt_path = tempfile.mkstemp(prefix="orch-local-capacity-", suffix=".json", dir=receipt_dir)
            with os.fdopen(fd, "w") as f:
                json.dump({"deferred": False}, f)
            child_env = dict(os.environ, ORCH_LOCAL_CAPACITY_RECEIPT=receipt_path)
            failure = None
            try:
                proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout_s, env=child_env)
            except subprocess.TimeoutExpired:
                _log(f"{name} TIMEOUT after {timeout_s}s")
                failure = {"rc": -1, "secs": timeout_s, "tail": ["timeout"]}
            except Exception as e:
                _log(f"{name} failed to launch: {type(e).__name__}")
                failure = {"rc": -2, "secs": 0, "tail": [type(e).__name__]}
            capacity_reason = _capacity_receipt(receipt_path)
        if capacity_reason:
            rc = failure["rc"] if failure else proc.returncode
            _log(f"{name} local capacity deferred: {capacity_reason}; rc={rc}; partial work possible; remains due")
            return {"status": "deferred" if rc == 0 else "failed",
                    "deferred": True, "partial": True, "reason": capacity_reason,
                    "rc": rc, "secs": failure["secs"] if failure else round(time.time() - t0), "tail": []}
        if failure:
            return failure
        tail = (proc.stdout or "").strip().splitlines()[-8:]
        err = (proc.stderr or "").strip().splitlines()[-3:]
        _log(f"{name} rc={proc.returncode} in {time.time() - t0:.0f}s" +
             ("\n    " + "\n    ".join(tail) if tail else "") +
             ("\n    stderr: " + " | ".join(err) if err and proc.returncode != 0 else ""))
        outcome = classify_outcome(name, proc.stdout, proc.returncode)
        return {"rc": proc.returncode, "secs": round(time.time() - t0), "tail": tail[-3:], **outcome}
    except subprocess.TimeoutExpired:
        _log(f"{name} TIMEOUT after {timeout_s}s")
        return {"rc": -1, "secs": timeout_s, "tail": ["timeout"]}
    except Exception as e:
        _log(f"{name} failed to launch: {type(e).__name__}: {e}")
        return {"rc": -2, "secs": 0, "tail": [str(e)[:120]]}


def _record_result(state, name, result):
    """Attempt, execution completion, reported production, and absorption are distinct.

    `at` retains the legacy scheduling timestamp; `last_attempt` remains retry-only
    for older consumers. `latest_attempt` is the honest receipt for every attempt.
    """
    now = time.time()
    previous = state.get(name)
    previous = previous if isinstance(previous, dict) else {}
    latest = {"at": now, **{k: result[k] for k in (
        "status", "reason", "rc", "secs", "partial", "execution_success", "evidence",
        "counters", "absorption", "value") if k in result}}
    latest.setdefault("status", "failed" if result.get("rc") not in (0, None) else "unverified")
    latest.setdefault("execution_success", result.get("rc") == 0)
    latest.setdefault("absorption", "unverified")
    latest.setdefault("value", "unverified")
    if result.get("deferred") is True:
        previous_attempt = previous.get("last_attempt") if isinstance(previous, dict) else None
        attempts = min(7, int(_finite_number(previous_attempt.get("attempts"))) + 1) if isinstance(previous_attempt, dict) else 1
        state[name] = {**(previous if isinstance(previous, dict) else {}),
                       "last_attempt": {"at": now, "attempts": attempts, "retry_after": now + _retry_delay(attempts), **{k: result[k] for k in
                                        ("status", "reason", "rc", "secs", "partial") if k in result}}}
    else:
        state[name] = {"at": now, **result,
                       **{k: previous[k] for k in ("last_productive_at", "last_productive_outcome") if k in previous}}
        if result.get("status") in ("produced", "work_done"):
            state[name]["last_productive_at"] = now
            state[name]["last_productive_outcome"] = latest
    state[name]["latest_attempt"] = latest
    _save(state)
    heartbeat(state)


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
        _record_result(state, name, res)
        return None if res.get("deferred") else name
    heartbeat(state)
    return None


def next_due(state, now=None):
    """The due job that is MOST overdue relative to its own interval. (2026-09-12: a fixed priority
    order let the 20-minute docket and the 30-minute commission take every slot — the theory lab,
    the corps tick, the forecaster and both scans had not run once in six hours. Never-run jobs
    sort first.) A deferral never advances completion, but does get bounded backoff and
    resets selection urgency so one permanently unavailable model cannot starve other jobs."""
    now = now or time.time()
    best, best_ratio = None, 0.0
    for job in JOBS:
        name, _script, _args, interval, _timeout = job
        st = state.get(name) or {}
        last = _finite_number(st.get("at"))
        if now - last < interval:
            continue
        attempt = st.get("last_attempt")
        attempted = 0
        if isinstance(attempt, dict):
            if _finite_number(attempt.get("retry_after")) > now:
                continue
            attempted = _finite_number(attempt.get("at"))
        selection_at = max(last, attempted)
        ratio = float("inf") if not selection_at else (now - selection_at) / float(interval)
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
                     "rc": st.get("rc"), "secs": st.get("secs"),
                     "last_attempt": st.get("last_attempt"),
                     "latest_attempt": st.get("latest_attempt"),
                     "last_productive_at": st.get("last_productive_at"),
                     "outcome_evidence": "reported_only; absorption and value unverified"})
    try:
        import frontier
        fb = frontier.status()
    except Exception as e:
        fb = {"error": str(e)}
    return {"paused": _paused(), "jobs": rows, "frontier": fb}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--status":
        print(json.dumps(status(), indent=2, default=str))
    elif len(argv) > 1 and argv[0] == "--once":
        want = argv[1]
        for name, script, args, interval, timeout_s in JOBS:
            if name == want:
                if _paused():
                    _log("kill switch paused — nothing run")
                    print(json.dumps({"status": "paused", "deferred": True, "reason": "kill_switch_paused", "rc": None}))
                    break
                res = run_job(name, script, (argv[2:] or args), timeout_s)
                _record_result(_load(), name, res)
                print(json.dumps(res, default=str))
                break
        else:
            print(f"unknown job {want}; known: {[j[0] for j in JOBS]}")
    else:
        ran = tick()
        _log(f"tick done: ran {ran or 'nothing (paused, deferred, or no job due)'}")


if __name__ == "__main__":
    main()
