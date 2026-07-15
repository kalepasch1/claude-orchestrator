#!/usr/bin/env python3
"""Durable operational history and health snapshot for the non-Cowork flow."""
from __future__ import annotations

import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import parallel_dispatch
import value_ledger
import flow_promotion
import hermetic_cas
import transformation_market
import proof_graph


def _runtime_path():
    home = os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__), "..", ".runtime"))
    return os.path.join(home, "secondary-flow-status.json")


def run(publish=True, limit=1000):
    rows = [r for r in value_ledger.recent(limit)
            if (r.get("metrics") or {}).get("lane") == "parallel-swarm"]
    real = [r for r in rows if not (
        r.get("task_id") == "t1" and r.get("slug") == "fast-fix" and r.get("project_id") == "p"
    )]
    stages = {stage: sum(r.get("stage") == stage for r in real)
              for stage in ("attempted", "verified", "integrated", "deployed", "rolled_back")}
    latest = real[-1] if real else None
    latest_verified = next((r for r in reversed(real) if r.get("stage") == "verified"), None)
    status = {
        "schema_version": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "enabled": parallel_dispatch.stats().get("enabled", False),
        "available_providers": parallel_dispatch.stats().get("available_providers", []),
        "events": len(real),
        "stages": stages,
        "verified_rate": round(stages["verified"] / max(1, stages["verified"] + stages["attempted"]), 4),
        "latest_event": latest,
        "latest_verified": latest_verified,
        "healthy": bool(latest_verified and time.time() - float(latest_verified.get("at") or 0) < 86400),
        "promotion": flow_promotion.decision(),
        "verification_cas": hermetic_cas.stats(),
        "transformation_market": transformation_market.stats(),
        "proof_graph": proof_graph.stats(),
    }
    path = _runtime_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(status, f, indent=2, default=str)
    os.replace(tmp, path)
    if publish:
        try:
            db.insert("controls", {"key": "secondary_flow", "value": json.dumps(status),
                                   "updated_at": "now()"}, upsert=True)
        except Exception:
            pass
    print("secondary-flow:", json.dumps(status, sort_keys=True, default=str))
    return status


if __name__ == "__main__":
    run()
