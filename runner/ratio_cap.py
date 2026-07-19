#!/usr/bin/env python3
"""Meta-work / product-work ratio cap.

Enforced at task insert time: tracks the ratio of meta-work tasks
(kind in recovery, release-fix, improve, rework, recover, cleanup, chore)
vs product-work tasks inserted in a rolling 24h window. If a new meta-work
task would push the ratio above ORCH_META_PRODUCT_RATIO_CAP, the task is
still inserted but at lowest priority (created_at pushed forward) and a
reason is logged on the task row.

Design choice: insert-with-demotion rather than reject, because meta-work
that is genuinely needed (recovery from a real breakage) should not be lost,
just deprioritised so product work gets lanes first.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

META_KINDS = {"recovery", "release-fix", "improve", "rework", "recover", "cleanup", "chore"}
DEFAULT_CAP = 0.5


def _cap():
    try:
        return max(0.0, min(1.0, float(os.environ.get("ORCH_META_PRODUCT_RATIO_CAP", str(DEFAULT_CAP)))))
    except Exception:
        return DEFAULT_CAP


def is_meta(kind):
    return (kind or "").lower().strip() in META_KINDS


def get_24h_counts(project_id=None):
    try:
        import db
        params = {"select": "kind", "created_at": f"gte.{_iso_24h_ago()}"}
        if project_id:
            params["project_id"] = f"eq.{project_id}"
        rows = db.select("tasks", params) or []
        meta = sum(1 for r in rows if is_meta(r.get("kind")))
        return meta, len(rows) - meta
    except Exception:
        return 0, 0


def _iso_24h_ago():
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()


def would_exceed_cap(meta_count, product_count, new_is_meta):
    if not new_is_meta:
        return False
    cap = _cap()
    if cap >= 1.0:
        return False
    if meta_count == 0 and product_count == 0:
        return False
    new_meta = meta_count + 1
    total = new_meta + product_count
    return new_meta / total > cap


def check_insert(kind, project_id=None):
    if not is_meta(kind):
        return True, ""
    meta, product = get_24h_counts(project_id)
    if would_exceed_cap(meta, product, new_is_meta=True):
        cap = _cap()
        current = meta / max(meta + product, 1)
        return False, (f"meta-work ratio {current:.2f} at cap {cap:.2f}; "
                       f"demoted to lowest priority ({meta} meta / {product} product in 24h)")
    return True, ""


def status():
    meta, product = get_24h_counts()
    total = meta + product
    return {"cap": _cap(), "meta_count_24h": meta, "product_count_24h": product,
            "current_ratio": round(meta / total, 3) if total else 0.0}
