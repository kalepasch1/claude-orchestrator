#!/usr/bin/env python3
"""
router_stats.py - a learned coder/vendor router. Reads our own outcomes and computes, per
(coder × task-kind), the merge-rate and $/merged-change, then recommends the vendor that actually
converts to merges most cheaply for a given kind of task. This closes the loop the doom-loop opened:
optimize cost-PER-MERGE from real results instead of guessing from per-call price.

Pure reads + a short cache; no model spend. `best_coder(kind, available)` returns a coder name to prefer,
or None when there isn't enough signal yet (so the default heuristic stays in charge). Fail-soft.
"""
import os, sys, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_CACHE = {"t": 0.0, "table": {}}
MIN_SAMPLES = int(os.environ.get("ROUTER_MIN_SAMPLES", "20"))
WINDOW_H = int(os.environ.get("ROUTER_WINDOW_H", "168"))  # 7 days


def _coder_of(model):
    m = str(model or "")
    return m.split(":", 1)[0] if ":" in m else ("claude" if m.startswith(("claude", "sonnet", "opus", "haiku")) else m)


def _rebuild():
    import datetime
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    rows = db.select("outcomes", {"select": "model,kind,integrated,usd,created_at,slug",
                                  "created_at": f"gte.{cutoff}", "limit": "5000"}) or []
    agg = collections.defaultdict(lambda: {"n": 0, "merged": 0, "usd": 0.0})
    for r in rows:
        s = str(r.get("slug") or "")
        if s.startswith("cont-") or s.startswith("batch-mech"):
            continue
        key = (_coder_of(r.get("model")), (r.get("kind") or "").lower() or "build")
        a = agg[key]
        a["n"] += 1
        a["usd"] += float(r.get("usd") or 0)
        if r.get("integrated"):
            a["merged"] += 1
    table = {}
    for (coder, kind), a in agg.items():
        if a["n"] < MIN_SAMPLES:
            continue
        rate = a["merged"] / a["n"]
        # cost per merge; when nothing merged, treat as very expensive (spend / 0.5 merge floor)
        cpm = a["usd"] / a["merged"] if a["merged"] else a["usd"] / 0.5 + 1000
        table.setdefault(kind, []).append({"coder": coder, "rate": round(rate, 3),
                                           "usd_per_merge": round(cpm, 3), "n": a["n"]})
    for kind in table:
        table[kind].sort(key=lambda x: (x["usd_per_merge"], -x["rate"]))
    return table


def _table():
    if time.time() - _CACHE["t"] < 300:
        return _CACHE["table"]
    try:
        _CACHE["table"] = _rebuild()
    except Exception:
        _CACHE["table"] = {}
    _CACHE["t"] = time.time()
    return _CACHE["table"]


def best_coder(kind, available):
    """Preferred coder for this task kind by empirical $/merge, restricted to `available`. None = defer."""
    if os.environ.get("ORCH_LEARNED_ROUTER", "true").lower() not in ("true", "1", "yes"):
        return None
    ranked = _table().get((kind or "build").lower()) or _table().get("build") or []
    for row in ranked:
        if row["coder"] in set(available) and row["rate"] > 0:
            return row["coder"]
    return None


if __name__ == "__main__":
    import json
    print(json.dumps(_table(), indent=2, default=str))
