#!/usr/bin/env python3
"""
router_stats.py - a learned coder/vendor router. Reads our own outcomes and computes, per
(coder × pipeline-stage), a routing score from merge/deploy rate, build/test pass rate,
retry count, latency, and $/merged-value. This closes the loop the doom-loop opened:
optimize cost-PER-DEPLOYED-VALUE from real results instead of guessing from per-call price.

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


def _stage_of(row):
    kind = str(row.get("kind") or "build").lower()
    slug = str(row.get("slug") or "").lower()
    note = str(row.get("note") or "").lower()
    model = str(row.get("model") or "").lower()
    blob = " ".join((kind, slug, note, model))
    if slug.startswith("recover-missing-branch"):
        return "recovery"
    if "buildfail" in blob or "build_fix" in blob or kind in ("bugfix",):
        return "build-fix"
    if "conflict" in blob or "rebase" in blob:
        return "merge-conflict"
    if kind in ("canary",):
        return "canary"
    if kind in ("mechanical", "docs", "chore", "test", "tests"):
        return "mechanical"
    if kind in ("security", "legal"):
        return kind
    return kind or "build"


def _rebuild():
    import datetime
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    try:
        rows = db.select("outcomes", {"select": "model,kind,integrated,tests_passed,usd,wall_ms,attempts,created_at,slug,input_tokens,output_tokens,diff_bytes,review_failures,deployed,deploy_status,train_outcome,note",
                                      "created_at": f"gte.{cutoff}", "order": "created_at.desc",
                                      "limit": "5000"}) or []
    except Exception:
        rows = db.select("outcomes", {"select": "model,kind,integrated,tests_passed,usd,wall_ms,attempts,created_at,slug,input_tokens,output_tokens",
                                      "created_at": f"gte.{cutoff}", "order": "created_at.desc",
                                      "limit": "5000"}) or []
    try:
        import route_evidence
        rows = route_evidence.dedupe_attribution_rows(rows)
    except Exception:
        pass
    agg = collections.defaultdict(lambda: {"n": 0, "merged": 0, "tests": 0, "usd": 0.0,
                                           "wall_ms": 0.0, "attempts": 0.0,
                                           "tokens": 0.0, "diff_bytes": 0.0,
                                           "review_failures": 0.0,
                                           "deployed_n": 0, "train_failed": 0})
    for r in rows:
        s = str(r.get("slug") or "")
        if s.startswith("cont-") or s.startswith("batch-mech"):
            continue
        key = (_coder_of(r.get("model")), _stage_of(r))
        a = agg[key]
        a["n"] += 1
        a["usd"] += float(r.get("usd") or 0)
        a["wall_ms"] += float(r.get("wall_ms") or 0)
        a["attempts"] += float(r.get("attempts") or 1)
        a["tokens"] += float(r.get("input_tokens") or 0) + float(r.get("output_tokens") or 0)
        a["diff_bytes"] += float(r.get("diff_bytes") or 0)
        a["review_failures"] += float(r.get("review_failures") or 0)
        if r.get("tests_passed"):
            a["tests"] += 1
        if r.get("integrated"):
            a["merged"] += 1
        if r.get("deployed") or str(r.get("deploy_status") or "").lower() in ("ready", "success", "deployed", "green"):
            a["merged"] += 0.5
            a["deployed_n"] += 1
        if str(r.get("train_outcome") or "").lower() in ("testfail", "conflict"):
            a["train_failed"] += 1
    table = {}
    for (coder, kind), a in agg.items():
        if a["n"] < MIN_SAMPLES:
            continue
        rate = a["merged"] / a["n"]
        test_rate = a["tests"] / a["n"]
        deployed_rate = a["deployed_n"] / a["n"]
        train_fail_rate = a["train_failed"] / a["n"]
        avg_attempts = a["attempts"] / a["n"]
        avg_wall_s = (a["wall_ms"] / a["n"]) / 1000.0 if a["n"] else 0.0
        tokens_per_diff = a["tokens"] / max(1.0, a["diff_bytes"])
        review_failures_per_merge = a["review_failures"] / max(1.0, a["merged"])
        # cost per merge; when nothing merged, treat as very expensive (spend / 0.5 merge floor)
        cpm = a["usd"] / a["merged"] if a["merged"] else a["usd"] / 0.5 + 1000
        latency_penalty = min(10.0, avg_wall_s / 600.0)
        retry_penalty = max(0.0, avg_attempts - 1.0) * 0.35
        token_penalty = min(3.0, tokens_per_diff / 2000.0)
        review_penalty = min(3.0, review_failures_per_merge * 0.5)
        # deployed_rate replaces raw test_rate: reward outcomes that shipped, not just tested.
        # train_fail_rate penalizes coders whose work passes tests but fails train integration.
        score = (rate * 3.0) + (deployed_rate * 1.5) - (train_fail_rate * 0.5) - cpm - latency_penalty - retry_penalty - token_penalty - review_penalty
        table.setdefault(kind, []).append({"coder": coder, "score": round(score, 4),
                                           "rate": round(rate, 3), "test_rate": round(test_rate, 3),
                                           "deployed_rate": round(deployed_rate, 3),
                                           "train_fail_rate": round(train_fail_rate, 3),
                                           "avg_attempts": round(avg_attempts, 2),
                                           "avg_wall_s": round(avg_wall_s, 1),
                                           "tokens_per_diff_byte": round(tokens_per_diff, 3),
                                           "review_failures_per_merge": round(review_failures_per_merge, 3),
                                           "usd_per_merge": round(cpm, 3), "n": a["n"]})
    for kind in table:
        table[kind].sort(key=lambda x: (-x["score"], x["usd_per_merge"], -x["rate"]))
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


def best_coder(kind, available, stage=None):
    """Preferred coder for this task/stage by empirical $/deployed-merge, restricted to `available`."""
    if os.environ.get("ORCH_LEARNED_ROUTER", "true").lower() not in ("true", "1", "yes"):
        return None
    ranked = _table().get((stage or kind or "build").lower()) or _table().get((kind or "build").lower()) or _table().get("build") or []
    for row in ranked:
        if row["coder"] in set(available) and row["rate"] > 0:
            return row["coder"]
    return None


if __name__ == "__main__":
    import json
    print(json.dumps(_table(), indent=2, default=str))
