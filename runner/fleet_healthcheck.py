#!/usr/bin/env python3
"""One-shot fleet health snapshot.

Written 2026-08-02 after a day where the fleet reported healthy while merge-train, preflight,
quarantine and remediate were all dead, 130 worktrees had exhausted the execution pool, and every
task was routed to a Claude account with no quota left. Each check below is a condition that was
true that day and that nothing surfaced.

Usage:  python3 fleet_healthcheck.py          # human-readable
        python3 fleet_healthcheck.py --json   # machine-readable
"""
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RUNTIME = os.path.join(os.path.dirname(HERE), ".runtime")


def _sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def collect():
    import db
    now = datetime.datetime.now(datetime.timezone.utc)
    h1 = (now - datetime.timedelta(hours=1)).isoformat()
    h24 = (now - datetime.timedelta(hours=24)).isoformat()

    out = {"at": now.isoformat()}
    for label, params in (
        ("queued", {"state": "eq.QUEUED"}),
        ("running", {"state": "eq.RUNNING"}),
        ("done_total", {"state": "eq.DONE"}),
        ("quarantined", {"state": "eq.QUARANTINED"}),
    ):
        try:
            out[label] = db.count("tasks", params)
        except Exception:
            out[label] = None
    for label, since in (("done_1h", h1), ("done_24h", h24)):
        try:
            out[label] = db.count("tasks", {"state": "eq.DONE", "updated_at": "gte.%s" % since})
        except Exception:
            out[label] = None
    for label, since in (("created_1h", h1), ("created_24h", h24)):
        try:
            out[label] = db.count("tasks", {"created_at": "gte.%s" % since})
        except Exception:
            out[label] = None

    out["worktrees"] = len(os.listdir(os.path.join(RUNTIME, "integration-worktrees"))) \
        if os.path.isdir(os.path.join(RUNTIME, "integration-worktrees")) else 0
    out["runner_alive"] = bool(_sh("pgrep -f 'Python runner.py' | head -1"))
    out["ollama_loaded"] = int(_sh("pgrep -c llama-server") or 0)
    out["disabled_jobs"] = list(_read_json("disabled_jobs.json").keys())

    # A .err file being *written* recently is not the same as a job failing: fleet_control logs
    # informational config-pin notices to stderr, and flagging those cried wolf on the first run.
    # Require an actual exception in the file's tail as well as a recent write.
    errs = _sh("cd %s/logs 2>/dev/null && for f in *.err; do "
               "[ -s \"$f\" ] && [ $(( ($(date +%%s) - $(stat -f %%m \"$f\")) / 60 )) -le 15 ] "
               "&& tail -25 \"$f\" | grep -qE '^[A-Za-z_.]*(Error|Exception):' "
               "&& echo ${f%%.err}; done" % RUNTIME)
    out["live_error_jobs"] = [e for e in errs.split("\n") if e]

    # Classification invariants. If these break, blocked tasks get categorised from their own
    # name again and the repair pipeline starts respawning them indefinitely — the single
    # largest source of the 2026-08-03 backlog, and invisible in every other metric here.
    rc = subprocess.run([sys.executable, os.path.join(HERE, "test_blocker_classification.py")],
                        capture_output=True, text=True)
    out["classification_invariants_ok"] = rc.returncode == 0

    # Repair mix: a healthy fleet repairs a variety of causes. One category dominating means the
    # classifier is probably matching on identity rather than evidence again.
    try:
        import db as _db
        import collections
        import datetime as _dt
        since = (datetime.datetime.now(datetime.timezone.utc) - _dt.timedelta(hours=3)).isoformat()
        rows = _db.select("tasks", {"select": "note", "updated_at": "gte.%s" % since,
                                    "limit": "400"}) or []
        mix = collections.Counter()
        for r in rows:
            note = str(r.get("note") or "")
            if note.startswith("agentic-repair:"):
                mix[note.split(":", 1)[1].split()[0]] += 1
        out["repair_mix_3h"] = dict(mix.most_common(6))
        total = sum(mix.values())
        out["repair_top_share"] = round(max(mix.values()) / total, 2) if total >= 20 else None
    except Exception:
        out["repair_mix_3h"] = {}
        out["repair_top_share"] = None
    return out


def _read_json(name):
    try:
        with open(os.path.join(RUNTIME, name)) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def verdict(s):
    """Conditions that were silently true during the 2026-08-02 outage."""
    bad = []
    if not s.get("runner_alive"):
        bad.append("runner is NOT running — nothing will execute")
    if (s.get("worktrees") or 0) > 40:
        bad.append("worktrees %s over the cap of 40 — execution slots exhausted" % s["worktrees"])
    if s.get("ollama_loaded"):
        bad.append("a local model is resident — it starves the box and gets the runner killed")
    if (s.get("done_1h") or 0) == 0 and (s.get("running") or 0) > 0:
        bad.append("tasks are RUNNING but nothing completed in an hour — dispatch is failing")
    created, done = s.get("created_24h") or 0, s.get("done_24h") or 1
    if created > done * 5:
        bad.append("generating %sx faster than completing (%s created vs %s done in 24h)"
                   % (round(created / max(done, 1)), created, done))
    if s.get("live_error_jobs"):
        bad.append("jobs erroring right now: %s" % ", ".join(s["live_error_jobs"][:6]))
    if s.get("classification_invariants_ok") is False:
        bad.append("blocker classification invariants FAILED — blocked tasks can be categorised "
                   "from their own name again, which respawns them indefinitely "
                   "(run test_blocker_classification.py)")
    if (s.get("repair_top_share") or 0) > 0.6:
        top = max(s.get("repair_mix_3h") or {"?": 0}, key=(s.get("repair_mix_3h") or {"?": 0}).get)
        bad.append("repairs are %d%% '%s' — one category dominating usually means the classifier "
                   "is matching on task identity rather than failure evidence"
                   % (round(s["repair_top_share"] * 100), top))
    return bad


if __name__ == "__main__":
    snap = collect()
    if "--json" in sys.argv:
        print(json.dumps({"snapshot": snap, "problems": verdict(snap)}, indent=2))
    else:
        for k, v in snap.items():
            print("  %-16s %s" % (k, v))
        problems = verdict(snap)
        print()
        print("VERDICT: healthy" if not problems else "VERDICT: %d problem(s)" % len(problems))
        for p in problems:
            print("  - %s" % p)
    sys.exit(1 if verdict(snap) else 0)
