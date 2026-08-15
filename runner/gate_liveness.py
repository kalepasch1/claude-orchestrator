#!/usr/bin/env python3
"""gate_liveness.py — REQUIREMENT E: no gate is allowed to be silently dead.

WHY THIS EXISTS
---------------
A build-gate parser broke and returned its default `False` for 18 days. Nothing
raised, nothing counted, nothing alarmed: the failure looked exactly like "no
builds passed". A gate that returns the same verdict for essentially every input
is either (a) reporting a real, total outage, or (b) broken — and BOTH deserve an
alarm within hours, not weeks.

So this module is deliberately generic. Any gate wraps its verdict in
`record(gate, verdict, subject)` and every gate then gets, for free:

  * DEGENERATE alarm  — one verdict covers > DEGENERATE_SHARE of a window with at
    least MIN_SAMPLES observations.
  * SILENT alarm      — a gate that is registered as always-on produced NO verdicts
    at all in the window (the parser didn't just answer wrong, it stopped running).

Recording is best-effort and never raises: a liveness probe must not be able to
take down the gate it is watching.
"""
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW_HOURS = int(os.environ.get("ORCH_GATE_LIVENESS_WINDOW_H", "24"))
DEGENERATE_SHARE = float(os.environ.get("ORCH_GATE_DEGENERATE_SHARE", "0.95"))
MIN_SAMPLES = int(os.environ.get("ORCH_GATE_MIN_SAMPLES", "20"))

# Gates that are expected to produce verdicts continuously. A gate listed here that
# emits ZERO verdicts in a window is alarmed as 'silent'.
ALWAYS_ON = [
    "preflight",
    "build_gate",
    "regression_guard",
    "improvement_ship_gate",
    "improvement_measurement_gate",
]


# OFF THE CRITICAL PATH (2026-08-15)
# ----------------------------------
# record() swallowed exceptions ("never let telemetry break the gate") but never bounded
# TIME, and that is the half that mattered. Each db.insert can spend ORCH_SUPABASE_TIMEOUT
# (15s) per attempt, times HTTP_RETRIES, across several fallback relay endpoints — a minute or
# more when the control plane is slow. There are 23 record() call sites, several of them inside
# per-branch merge gates, so a single train pass pays that toll dozens of times.
#
# Measured today: the merge train had produced ZERO merges in 24 hours. The watchdog had fired
# 56 times at the 900s pass cap, and of those dumps, 11 were stopped precisely here —
# gate_liveness.record -> db.insert -> urlopen — with another 14 in the regression gate that
# calls it. Telemetry about whether the gates are alive was the single biggest reason the gates
# never finished running.
#
# So: hand the write to a background worker and return immediately. Liveness data is worth
# collecting and worth nothing at all if collecting it stops the pipeline it measures. On
# overflow we drop and say so once, because a queue that grows without bound to preserve
# telemetry would just be the same bug wearing a hat.
_QUEUE_MAX = int(os.environ.get("ORCH_GATE_LIVENESS_QUEUE", "512") or 512)
_queue = queue.Queue(maxsize=_QUEUE_MAX)
_worker = None
_worker_lock = threading.Lock()
_dropped = [0]


def _drain():
    while True:
        row = _queue.get()
        try:
            db.insert("orch_gate_verdicts", row)
        except Exception as exc:
            print(f"[gate_liveness] record failed for {row.get('gate')}: {exc}", flush=True)
        finally:
            _queue.task_done()


def _ensure_worker():
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain, name="gate-liveness", daemon=True)
            _worker.start()


def record(gate, verdict, subject=None, detail=None):
    """Persist one gate verdict. Non-blocking; returns the verdict unchanged.

    Designed to be used inline:  return gate_liveness.record("build_gate", ok, slug)

    The write happens on a background thread. The caller is never delayed by the control
    plane, which is the whole point — see the note above this function.
    """
    try:
        _ensure_worker()
        _queue.put_nowait({
            "gate": str(gate)[:120],
            "verdict": _norm(verdict),
            "subject": (str(subject)[:200] if subject is not None else None),
            "detail": (str(detail)[:500] if detail is not None else None),
        })
    except queue.Full:
        _dropped[0] += 1
        if _dropped[0] == 1 or _dropped[0] % 100 == 0:
            print(f"[gate_liveness] telemetry queue full; dropped {_dropped[0]} verdict(s) "
                  f"rather than delay the gate", flush=True)
    except Exception as exc:            # never let telemetry break the gate
        print(f"[gate_liveness] record failed for {gate}: {exc}", flush=True)
    return verdict


def flush(timeout=10.0):
    """Best-effort drain, for a process that is about to exit. Never raises."""
    try:
        deadline = time.monotonic() + max(0.0, float(timeout))
        while not _queue.empty() and time.monotonic() < deadline:
            time.sleep(0.05)
        return _queue.empty()
    except Exception:
        return False


def _norm(verdict):
    if isinstance(verdict, bool):
        return "true" if verdict else "false"
    return str(verdict)[:80]


def _since_iso(hours):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))


def verdict_histogram(gate, hours=WINDOW_HOURS):
    """{verdict: count} for `gate` over the trailing window."""
    rows = db.select("orch_gate_verdicts", {
        "select": "verdict",
        "gate": f"eq.{gate}",
        "created_at": f"gte.{_since_iso(hours)}",
        "limit": "20000",
    }) or []
    hist = {}
    for r in rows:
        v = r.get("verdict") or "?"
        hist[v] = hist.get(v, 0) + 1
    return hist


def assess(gate, hours=WINDOW_HOURS, min_samples=MIN_SAMPLES, share=DEGENERATE_SHARE):
    """Assess ONE gate. Returns a dict; `alarm` is None, 'degenerate' or 'silent'."""
    hist = verdict_histogram(gate, hours)
    n = sum(hist.values())
    if n == 0:
        kind = "silent" if gate in ALWAYS_ON else None
        return {"gate": gate, "n": 0, "alarm": kind, "verdict": None, "share": None,
                "hist": hist, "window_hours": hours}
    top_verdict, top_n = max(hist.items(), key=lambda kv: kv[1])
    top_share = top_n / n
    alarm = "degenerate" if (n >= min_samples and top_share > share) else None
    return {"gate": gate, "n": n, "alarm": alarm, "verdict": top_verdict,
            "share": round(top_share, 4), "hist": hist, "window_hours": hours}


def _known_gates(hours):
    rows = db.select("orch_gate_verdicts", {
        "select": "gate", "created_at": f"gte.{_since_iso(hours)}", "limit": "20000"}) or []
    return sorted({r.get("gate") for r in rows if r.get("gate")} | set(ALWAYS_ON))


def _open_alarm(gate, kind):
    rows = db.select("orch_gate_alarms", {
        "select": "id", "gate": f"eq.{gate}", "kind": f"eq.{kind}",
        "resolved_at": "is.null", "limit": "1"}) or []
    return rows[0] if rows else None


def raise_or_resolve(a):
    """Open an alarm when one is warranted, resolve it when the gate recovers.

    Idempotent: re-running never duplicates an open alarm.
    """
    gate, kind = a["gate"], a["alarm"]
    for existing_kind in ("degenerate", "silent"):
        row = _open_alarm(gate, existing_kind)
        if row and existing_kind != kind:
            db.update("orch_gate_alarms", {"id": row["id"]}, {"resolved_at": "now()"})
    if not kind:
        return None
    if _open_alarm(gate, kind):
        return None                      # already open — don't spam
    detail = (f"gate '{gate}' returned {a['verdict']!r} for {a['share']:.1%} of {a['n']} "
              f"inputs in {a['window_hours']}h" if kind == "degenerate"
              else f"gate '{gate}' produced NO verdicts in {a['window_hours']}h")
    db.insert("orch_gate_alarms", {
        "gate": gate, "kind": kind, "verdict": a.get("verdict"),
        "share": a.get("share"), "n": a.get("n"), "window_hours": a.get("window_hours"),
        "detail": detail[:500]})
    print(f"[gate_liveness] ALARM ({kind}): {detail}", flush=True)
    return {"gate": gate, "kind": kind, "detail": detail}


def sweep(hours=WINDOW_HOURS):
    """Assess every gate seen in the window plus every ALWAYS_ON gate."""
    assessments, alarms = [], []
    for gate in _known_gates(hours):
        a = assess(gate, hours)
        assessments.append(a)
        fired = raise_or_resolve(a)
        if fired:
            alarms.append(fired)
    return {"assessed": len(assessments), "alarms": alarms, "detail": assessments}


def run():
    out = sweep()
    print(f"gate_liveness: assessed {out['assessed']} gates; {len(out['alarms'])} alarm(s)")
    for a in out["detail"]:
        flag = a["alarm"] or "ok"
        print(f"  {a['gate']:<32} n={a['n']:<6} top={a['verdict']} "
              f"share={a['share']} -> {flag}")
    return out


if __name__ == "__main__":
    run()
