#!/usr/bin/env python3
"""Route performance objective: deployed/merged value per minute per coder/stage."""
import collections
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import router_stats

WINDOW_H = int(os.environ.get("ROUTE_PERF_WINDOW_H", "168"))
BACKFILL = os.environ.get("ROUTE_PERF_BACKFILL", "true").lower() in ("1", "true", "yes", "on")


def summarize():
    if BACKFILL:
        try:
            import route_evidence
            route_evidence.backfill_merged()
        except Exception:
            pass
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    try:
        rows = db.select("outcomes", {"select": "model,kind,slug,note,integrated,tests_passed,usd,wall_ms,attempts,deployed,deploy_status",
                                      "created_at": f"gte.{since}", "order": "created_at.desc",
                                      "limit": "5000"}) or []
    except Exception:
        rows = db.select("outcomes", {"select": "model,kind,slug,integrated,tests_passed,usd,wall_ms,attempts",
                                      "created_at": f"gte.{since}", "order": "created_at.desc",
                                      "limit": "5000"}) or []
    try:
        import route_evidence
        rows = route_evidence.dedupe_attribution_rows(rows)
    except Exception:
        pass
    agg = collections.defaultdict(lambda: {"n": 0, "tests": 0, "merged": 0.0, "usd": 0.0, "minutes": 0.0})
    for r in rows:
        key = (router_stats._coder_of(r.get("model")), router_stats._stage_of(r))
        a = agg[key]
        a["n"] += 1
        a["tests"] += 1 if r.get("tests_passed") else 0
        merged = 1.0 if r.get("integrated") else 0.0
        if r.get("deployed") or str(r.get("deploy_status") or "").lower() in ("ready", "success", "deployed", "green"):
            merged += 0.5
        a["merged"] += merged
        a["usd"] += float(r.get("usd") or 0)
        a["minutes"] += max(0.01, float(r.get("wall_ms") or 0) / 60000.0)
    out = []
    for (coder, stage), a in agg.items():
        out.append({"coder": coder, "stage": stage, "n": a["n"],
                    "test_rate": round(a["tests"] / max(1, a["n"]), 3),
                    "merged_value": round(a["merged"], 2),
                    "merged_value_per_min": round(a["merged"] / max(1.0, a["minutes"]), 4),
                    "usd_per_merged_value": round(a["usd"] / max(0.5, a["merged"]), 4)})
    out.sort(key=lambda r: (-r["merged_value_per_min"], r["usd_per_merged_value"], -r["n"]))
    return out


def run():
    rows = summarize()
    payload = {"performance": rows[:40]}
    try:
        import route_evidence
        payload["evidence"] = route_evidence.evidence_summary()
    except Exception:
        pass
    print(json.dumps(payload, indent=2, default=str))
    return rows


if __name__ == "__main__":
    run()
