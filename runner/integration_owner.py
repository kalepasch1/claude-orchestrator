#!/usr/bin/env python3
"""
integration_owner.py — decide, fleet-wide, WHICH host is allowed to integrate.

WHY (2026-08-06)
----------------
Two failure modes, both measured on this fleet, both caused by the multi-Mac setup
having no cross-host coordination for the one operation that touches shared state
(pushing to GitHub):

  1. NO CROSS-HOST MUTUAL EXCLUSION. `integration_runtime.global_lease()` is a flock on
     a file under each machine's own .runtime/. It serialises processes on ONE Mac and
     is completely blind to the other. Both Macs therefore ran merge trains against the
     same origin simultaneously, producing 54 PUSH-VERIFY-FAILED sha-mismatches —
     including the public-landing-hero copyfix task, i.e. real product work destroyed
     by a race.

  2. STALE HOSTS SHIPPING. Mac 2 sat on 10d9e408 for days, 32 commits behind, missing
     every merge-train fix. It kept merging and pushing with known-broken logic, undoing
     work the current host had just fixed.

Both are solved by the same rule: exactly ONE host integrates at a time, and it must be
running current code. Everything else (claiming tasks, running agents, tests) stays fully
parallel across all Macs — that is where the multi-Mac advantage actually lives, and it
involves no shared mutable state.

DESIGN
------
Ownership is decided from `runner_heartbeats`, which every host already writes:

  * An explicit override wins: ORCH_INTEGRATION_HOST (settable from ANY Mac via
    fleet_config, so the fleet can be steered from whichever machine you happen to be on).
  * Otherwise the owner is AUTO-ELECTED as the live host running the newest code, ties
    broken by hostname so every host independently computes the SAME winner without
    needing to talk to each other.
  * A host whose own code is behind the fleet maximum never integrates, even if elected.

This is deliberately a *pure function of shared state* rather than a distributed lock:
there is no lease to leak, no TTL to tune, and no way for a crashed owner to wedge the
fleet — if the owner stops heartbeating it drops out of `live` and the next host elects
itself within HEARTBEAT_STALE_S.
"""
import os
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HOST = socket.gethostname()
HEARTBEAT_STALE_S = int(os.environ.get("ORCH_HEARTBEAT_STALE_S", "300"))
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def local_code_sha():
    """Full git HEAD of this checkout, or '' when git is unavailable."""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO,
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _live_hosts():
    """{hostname: code_sha} for hosts that heartbeat recently. Newest row per host wins."""
    import datetime
    try:
        rows = db.select("runner_heartbeats",
                         {"select": "hostname,code_sha,last_seen",
                          "order": "last_seen.desc", "limit": "60"}) or []
    except Exception:
        return {}
    now = datetime.datetime.now(datetime.timezone.utc)
    out = {}
    for r in rows:
        h = (r.get("hostname") or "").strip()
        if not h or h in out:
            continue
        ts = str(r.get("last_seen") or "")
        try:
            seen = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=datetime.timezone.utc)
            if (now - seen).total_seconds() > HEARTBEAT_STALE_S:
                continue
        except Exception:
            pass          # unparseable timestamp: treat as live rather than silently drop a host
        out[h] = (r.get("code_sha") or "").strip()
    return out


def decide(local_sha=None):
    """Return (may_integrate: bool, reason: str). Never raises."""
    try:
        mine = (local_sha if local_sha is not None else local_code_sha()) or ""
        override = (os.environ.get("ORCH_INTEGRATION_HOST") or "").strip()
        live = _live_hosts()

        # An explicit owner set from any Mac (fleet_config -> env) is authoritative.
        if override:
            if override in ("all", "any"):
                return True, "override: all hosts may integrate"
            ok = override == HOST or override in (HOST.split(".")[0],)
            return ok, (f"override owner={override}" + ("" if ok else f"; this host is {HOST}"))

        if not live:
            # Control plane unreadable: integrating is safer than a fleet-wide stall, and the
            # push-verify check downstream still catches a race after the fact.
            return True, "no heartbeat data; proceeding (fail-open)"

        # STALE-CODE GUARD: never let an out-of-date host mutate shared refs.
        shas = {s for s in live.values() if s}
        if mine and shas and len(shas) > 1:
            newest = _newest_sha(live)
            if newest and mine != newest and _is_behind(mine, newest):
                return False, (f"stale code: this host is on {mine[:8]}, fleet has {newest[:8]} "
                               f"— executing is fine, integrating is not")

        owner = _elect(live)
        if owner and owner != HOST:
            return False, f"integration owner is {owner}"
        return True, f"integration owner is this host ({HOST})"
    except Exception as exc:                       # never wedge the train on a control-plane hiccup
        return True, f"owner check failed ({exc}); proceeding"


def _newest_sha(live):
    """The sha that is an ancestor of no other live sha (i.e. the tip)."""
    shas = [s for s in live.values() if s]
    best = ""
    for s in shas:
        if not best:
            best = s
            continue
        if _is_behind(best, s):
            best = s
    return best


def _is_behind(a, b):
    """True when commit `a` is strictly an ancestor of `b` in this checkout."""
    if not a or not b or a == b:
        return False
    try:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", a, b],
                           cwd=_REPO, capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def _elect(live):
    """Deterministic owner: newest code wins, hostname breaks ties. Same answer on every host."""
    if not live:
        return ""
    newest = _newest_sha(live)
    candidates = [h for h, s in live.items() if s == newest] if newest else sorted(live)
    return sorted(candidates)[0] if candidates else ""


if __name__ == "__main__":
    ok, why = decide()
    print(f"host={HOST}")
    print(f"local_sha={local_code_sha()[:10]}")
    print(f"live={ { h: s[:8] for h, s in _live_hosts().items() } }")
    print(f"may_integrate={ok}  reason={why}")
