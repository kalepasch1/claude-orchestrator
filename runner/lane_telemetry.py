#!/usr/bin/env python3
"""
lane_telemetry.py — the third bullet of the fleet immune system: make the lane
population and the mem-gate VISIBLE, and page the operator when either goes bad.

WHY THIS EXISTS
---------------
The 2026-08-02 incident had two halves. Half one — 64 of 66 lanes were zombies and
legal_docket had leaked 14 copies — is fixed by lane_guard.py (hard wall-clock +
heartbeat kill) and single_instance.py (flock per interval script). Those stop the
fleet from filling with dead workers.

Half two is why it ran for hours before anyone knew. The runner mem-gate was doing
its job perfectly: RAM was genuinely starved, so it held claims (claimable=803,
claiming ~0). Nothing was broken enough to crash and nothing was healthy enough to
progress, and the fleet sat in that state, silently, because a correctly-closed
mem-gate looks exactly like a quiet fleet from the outside.

So this module answers two questions that nothing else answered:

    "how many lanes are alive, and how old are they?"
    "is the mem-gate closed, and for HOW LONG?"

Duration is the entire point of the second one. A mem-gate that closes for ninety
seconds under a heavy typecheck is the gate working. A mem-gate closed for fifteen
minutes is an outage wearing the costume of a working gate. Only elapsed time tells
those apart, which is why _GateClock persists closed-since across ticks.

CONTRACT REUSE
--------------
Thresholds are NOT redefined here. fleet_immune_contracts.py owns what "zombie" and
"lane count is high" mean, and runner/tools/lane_medic.sh already reads the same env
vars with the same defaults precisely so the stopgap and the durable path can never
disagree. This module imports the contract rather than repeating its numbers; the two
values it does own (the alert slack over throttle, and the mem-gate patience window)
are the ones the operator directive states literally: "lanes>throttle+5 or mem-gate
closed >15 min".

FAIL-SOFT, LIKE ITS SIBLINGS
----------------------------
Telemetry that can crash the runner it observes is worse than no telemetry. Every
public function returns a usable default on any error and logs the reason; none of
them raise. A broad except here always writes a diagnostic first — a silent
`except: pass` would reproduce the exact bug this module exists to prevent.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NAME = "lane-telemetry"

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))

# ── the two thresholds the operator directive names literally ────────────────────────────
# "Alert ... when lanes>throttle+5 or mem-gate closed >15 min".
def _int_env(key, default):
    """Env int with a fail-soft floor. A garbage central push must not disable an alert."""
    try:
        value = int(float(os.environ.get(key, "") or default))
        return value if value >= 0 else int(default)
    except Exception as exc:
        print(f"[{NAME}] bad {key} ({exc}); using {default}", flush=True)
        return int(default)


def lane_alert_slack():
    """How far above the current throttle the lane count may sit before paging."""
    return _int_env("ORCH_LANE_ALERT_SLACK", 5)


def memgate_alert_seconds():
    """How long the mem-gate may stay closed before paging."""
    return _int_env("ORCH_MEMGATE_ALERT_S", 15 * 60)


# Age histogram buckets, in seconds. The last bucket is open-ended. These are display
# buckets only — reaping decisions belong to the contract, never to a chart.
AGE_BUCKETS_S = (5 * 60, 15 * 60, 30 * 60, 60 * 60)


def age_histogram(lanes, now=None, buckets=AGE_BUCKETS_S):
    """{bucket_label: count} over lane ages. Never raises.

    The histogram is what distinguishes "eight lanes working" from "eight lanes dead":
    a healthy fleet is bottom-heavy, and the incident fleet was 64 lanes all older than
    an hour. A bare count cannot tell those apart, which is why the count alone was not
    enough to notice for hours.
    """
    labels = [f"<{b // 60}m" for b in buckets] + [f">={buckets[-1] // 60}m"]
    hist = {label: 0 for label in labels}
    try:
        reference = time.time() if now is None else now
        for lane in lanes or ():
            age = getattr(lane, "age_s", None)
            if age is None and isinstance(lane, dict):
                age = lane.get("age_s")
            try:
                age = float(age or 0.0)
            except Exception:
                age = 0.0
            if age < 0:
                age = 0.0
            for idx, bound in enumerate(buckets):
                if age < bound:
                    hist[labels[idx]] += 1
                    break
            else:
                hist[labels[-1]] += 1
        _ = reference  # `now` is accepted for callers that pass absolute times
    except Exception as exc:
        print(f"[{NAME}] age_histogram failed ({exc}); returning empty buckets", flush=True)
    return hist


def reaps_per_hour(reap_times, now=None, window_s=3600):
    """Reaps observed in the trailing window, scaled to an hourly rate. Never raises.

    A rising reap rate is the fleet's fever: lane_guard is doing its job, but something
    upstream keeps producing lanes that need killing. The reaps are the symptom worth
    watching even when the lane count looks fine, because the guard is holding the count
    down by force.
    """
    try:
        reference = time.time() if now is None else float(now)
        window = float(window_s) if float(window_s) > 0 else 3600.0
        recent = 0
        for stamp in reap_times or ():
            try:
                ts = float(stamp)
            except Exception:
                continue
            if reference - ts <= window:
                recent += 1
        return round(recent * (3600.0 / window), 2)
    except Exception as exc:
        print(f"[{NAME}] reaps_per_hour failed ({exc}); reporting 0", flush=True)
        return 0.0


class _GateClock:
    """Remembers when the mem-gate closed, so duration survives across ticks.

    Module-level singleton (see `_clock` below): callers use the module functions and
    never construct this. State is mirrored to a file because the runner that observes
    the gate is not necessarily the process that started when the gate closed — losing
    closed-since on restart would reset the fifteen-minute clock forever, which is the
    one way this alert could never fire.
    """

    def __init__(self, path=None):
        self.path = path or os.path.join(HOME, "lane-telemetry-gate.json")
        self._closed_since = None

    def _load(self):
        if self._closed_since is not None:
            return self._closed_since
        try:
            with open(self.path) as fh:
                value = json.load(fh).get("closed_since")
            self._closed_since = float(value) if value else None
        except FileNotFoundError:
            self._closed_since = None
        except Exception as exc:
            print(f"[{NAME}] gate state unreadable ({exc}); starting a fresh clock",
                  flush=True)
            self._closed_since = None
        return self._closed_since

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"closed_since": self._closed_since}, fh)
            os.replace(tmp, self.path)
        except Exception as exc:
            print(f"[{NAME}] could not persist gate state ({exc})", flush=True)

    def observe(self, closed, now=None):
        """Record the current gate state; return seconds closed (0.0 when open)."""
        reference = time.time() if now is None else float(now)
        if not closed:
            if self._load() is not None or self._closed_since is not None:
                self._closed_since = None
                self._save()
            return 0.0
        if self._load() is None:
            self._closed_since = reference
            self._save()
        return max(0.0, reference - float(self._closed_since))

    def reset(self):
        self._closed_since = None
        self._save()


_clock = _GateClock()


def observe_mem_gate(closed, now=None):
    """Seconds the mem-gate has been continuously closed (0.0 when open)."""
    try:
        return _clock.observe(bool(closed), now=now)
    except Exception as exc:
        print(f"[{NAME}] gate clock failed ({exc}); reporting 0s closed", flush=True)
        return 0.0


def reset_gate_clock():
    """Test/ops hook: forget the closed-since mark."""
    try:
        _clock.reset()
    except Exception as exc:
        print(f"[{NAME}] gate clock reset failed ({exc})", flush=True)


def evaluate_alerts(lane_count, throttle, gate_closed_s, free_gb=None, floor_gb=None,
                    slack=None, patience_s=None):
    """The two operator-specified alerts. Returns a list of dicts; never raises.

    Deliberately NOT a reaper. This module observes and pages; killing lanes belongs to
    lane_guard, and an observer that also acts is an observer that can cause the incident
    it is supposed to report.
    """
    alerts = []
    try:
        slack = lane_alert_slack() if slack is None else int(slack)
        patience = memgate_alert_seconds() if patience_s is None else float(patience_s)
        try:
            lanes = int(lane_count or 0)
        except Exception:
            lanes = 0
        try:
            limit = int(throttle or 0)
        except Exception:
            limit = 0

        if limit > 0 and lanes > limit + slack:
            alerts.append({
                "kind": "lane_count_over_throttle",
                "severity": "warn",
                "detail": (f"{lanes} lanes alive against throttle {limit} "
                           f"(+{slack} slack) — lanes are outliving their tasks"),
                "lanes": lanes, "throttle": limit, "slack": slack,
            })

        try:
            closed_s = float(gate_closed_s or 0.0)
        except Exception:
            closed_s = 0.0
        if closed_s > patience:
            ram = ""
            if free_gb is not None:
                ram = f" free={float(free_gb):.1f}GB"
                if floor_gb is not None:
                    ram += f" floor={float(floor_gb):.1f}GB"
            alerts.append({
                "kind": "mem_gate_closed_too_long",
                "severity": "critical",
                "detail": (f"mem-gate closed {int(closed_s // 60)}m "
                           f"(> {int(patience // 60)}m): claims are held fleet-wide"
                           f" and no one has been told.{ram}"),
                "closed_s": closed_s, "patience_s": patience,
                "free_gb": free_gb, "floor_gb": floor_gb,
            })
    except Exception as exc:
        print(f"[{NAME}] evaluate_alerts failed ({exc}); no alerts raised", flush=True)
    return alerts


def emit(alerts, host=None):
    """Record alerts in runner_alerts and ping the operator. Never raises.

    Both sinks are attempted independently: a DB blip must not also cost the operator
    ping, and vice versa. Silence is the failure mode this whole module exists to end,
    so an unwritable sink is logged loudly rather than swallowed.
    """
    sent = 0
    for alert in alerts or ():
        detail = f"host={host or _hostname()} — {alert.get('detail', '')}"[:2000]
        try:
            import db
            db.insert("runner_alerts", {
                "kind": alert.get("kind", "lane_telemetry"),
                "detail": detail,
                "resolved": False,
            })
            sent += 1
        except Exception as exc:
            print(f"[{NAME}] could not record alert ({exc}): {detail}", flush=True)
        try:
            import notify
            notify.send(f"[{NAME}] {detail}")
        except Exception as exc:
            print(f"[{NAME}] could not ping operator ({exc})", flush=True)
    return sent


def _hostname():
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "?"


def _gate_reading():
    """(closed, free_gb, floor_gb, throttle) from the governor. Fail-soft to unknowns."""
    closed, free_gb, floor_gb, throttle = False, None, None, 0
    try:
        import resource_governor as rg
        try:
            free_gb = rg.free_ram_gb()
        except Exception:
            free_gb = None
        try:
            floor_gb = rg.effective_floor_gb()
        except Exception:
            floor_gb = None
        try:
            ok, _why = rg.can_claim()
            closed = not ok
        except Exception:
            closed = False
        try:
            throttle = int(rg.current_limit())
        except Exception:
            throttle = 0
    except Exception as exc:
        print(f"[{NAME}] governor unreadable ({exc}); reporting gate open", flush=True)
    return closed, free_gb, floor_gb, throttle


def snapshot(lanes=(), reap_times=(), now=None):
    """The SLO-dashboard payload: lane count, age histogram, reaps/hour, gate state.

    Shaped as plain JSON-safe types on purpose — it crosses a process boundary to the
    dashboard, and the fleet already learned once (train-stale, false alarm for days)
    what happens when a producer and a consumer disagree about where the truth lives.
    """
    closed, free_gb, floor_gb, throttle = _gate_reading()
    closed_s = observe_mem_gate(closed, now=now)
    lanes = list(lanes or ())
    payload = {
        "host": _hostname(),
        "observed_at": time.time() if now is None else float(now),
        "lane_count": len(lanes),
        "lane_age_histogram": age_histogram(lanes, now=now),
        "reaps_per_hour": reaps_per_hour(reap_times, now=now),
        "mem_gate": {
            "closed": bool(closed),
            "closed_s": closed_s,
            "free_gb": free_gb,
            "floor_gb": floor_gb,
        },
        "throttle": throttle,
    }
    payload["alerts"] = evaluate_alerts(
        len(lanes), throttle, closed_s, free_gb=free_gb, floor_gb=floor_gb)
    return payload


def tick(lanes=(), reap_times=(), now=None, emit_alerts=True):
    """One observation: build the snapshot, page on anything it flags."""
    payload = snapshot(lanes=lanes, reap_times=reap_times, now=now)
    if emit_alerts and payload.get("alerts"):
        payload["alerts_emitted"] = emit(payload["alerts"], host=payload.get("host"))
    return payload


if __name__ == "__main__":
    print(json.dumps(tick(emit_alerts="--emit" in sys.argv), indent=2, default=str))
