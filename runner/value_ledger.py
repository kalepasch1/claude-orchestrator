#!/usr/bin/env python3
"""Append-only causal value-contract ledger.

Engineering events (generated, tested, integrated, deployed) are deliberately
separate from product effects.  This prevents a merge from being silently counted
as delivered business value while still supporting projects without revenue KPIs.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

import control_plane

_lock = threading.Lock()


def _path():
    home = os.environ.get(
        "CLAUDE_ORCH_HOME",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime"),
    )
    return os.path.join(home, "value-ledger.jsonl")


def append(task: dict, stage: str, observed: bool, **metrics):
    row = {
        "event_id": str(uuid.uuid4()),
        "schema_version": 2,
        "at": time.time(),
        "task_id": task.get("id"),
        "slug": task.get("slug"),
        "project_id": task.get("project_id"),
        "objective": control_plane.objective_fingerprint(task),
        "contract": control_plane.outcome_contract(task),
        "stage": stage,
        "observed": bool(observed),
        "metrics": metrics,
    }
    try:
        path = _path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock, open(path, "a") as f:
            f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass
    return row


def record_execution(task: dict, tests_passed: bool, integrated: bool, **metrics):
    return append(
        task, "integrated" if integrated else "verified" if tests_passed else "attempted",
        observed=True, tests_passed=bool(tests_passed), integrated=bool(integrated), **metrics,
    )


def record_deployment(project: str, release: dict, success: bool, **metrics):
    synthetic = {
        "id": release.get("id"), "slug": f"release:{release.get('to_sha') or release.get('id')}",
        "project_id": project, "kind": "deploy", "prompt": release.get("note") or "production release",
        "material": True,
    }
    return append(synthetic, "deployed" if success else "rolled_back", observed=True,
                  success=bool(success), commit=release.get("to_sha"), **metrics)


def recent(limit: int = 1000):
    try:
        with open(_path()) as f:
            lines = f.readlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]
    except Exception:
        return []


def summary(limit: int = 1000):
    rows = recent(limit)
    return {
        "events": len(rows),
        "verified": sum(r.get("stage") == "verified" for r in rows),
        "integrated": sum(r.get("stage") == "integrated" for r in rows),
        "deployed": sum(r.get("stage") == "deployed" for r in rows),
        "rolled_back": sum(r.get("stage") == "rolled_back" for r in rows),
        "pending_product_observation": sum(
            r.get("stage") == "deployed" and r.get("contract", {}).get("primary") == "measured_product_delta"
            for r in rows
        ),
    }


def purge_test_records():
    """Remove the historical fixture emitted by an old verification test.

    New tests isolate CLAUDE_ORCH_HOME, but seven earlier test runs wrote their
    fixed ``t1/fast-fix`` fixture into the canonical runtime ledger.  Restrict the
    cleanup to that exact tuple so no operator or production event is touched.
    """
    path = _path()
    try:
        with _lock, open(path) as f:
            rows = [json.loads(line) for line in f if line.strip()]
        kept = [r for r in rows if not (
            r.get("task_id") == "t1" and r.get("slug") == "fast-fix"
            and r.get("project_id") == "p"
        )]
        tmp = path + ".clean"
        with _lock, open(tmp, "w") as f:
            for row in kept:
                f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
        os.replace(tmp, path)
        return {"removed": len(rows) - len(kept), "kept": len(kept)}
    except OSError:
        return {"removed": 0, "kept": 0}


if __name__ == "__main__":
    print(json.dumps(summary(), indent=2))
