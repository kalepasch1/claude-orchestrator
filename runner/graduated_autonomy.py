#!/usr/bin/env python3
"""
graduated_autonomy.py — Graduated autonomy by outcome history (50X-200X gate savings).

Tasks from a proven template class (>95% merge rate, >10 merges) can skip gates
progressively based on empirical trust:

  Level 0: Full gates (verify + judge + build + confidence)  — new/unknown patterns
  Level 1: Skip judge (verify + build + confidence)          — 5+ merges, >80% rate
  Level 2: Skip judge + verify (build + confidence only)     — 10+ merges, >90% rate
  Level 3: Skip all gates except build                       — 15+ merges, >95% rate
  Level 4: Skip ALL gates including build                    — 20+ merges, >98% rate, 0 rollbacks

Each level is earned per (task_class × domain × model) triple. A single rollback
drops the triple back to Level 0 immediately.

Usage:
    import graduated_autonomy
    level = graduated_autonomy.trust_level(task, agent_id, domain)
    gates_to_skip = graduated_autonomy.gates_to_skip(level)
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Trust level thresholds
LEVELS = [
    # (min_merges, min_merge_rate, max_rollbacks, level)
    (20, 0.98, 0, 4),  # skip ALL gates
    (15, 0.95, 0, 3),  # skip all except build
    (10, 0.90, 1, 2),  # skip judge + verify
    (5,  0.80, 2, 1),  # skip judge only
]


def _trust_data():
    """Load trust data from controls."""
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.graduated_trust"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_trust(data):
    try:
        db.upsert("controls", {"key": "graduated_trust", "value": json.dumps(data, default=str)})
    except Exception:
        pass


def _trust_key(task_class, domain, agent_id):
    return f"{task_class}:{domain}:{agent_id}"


def trust_level(task, agent_id="", domain="backend"):
    """Compute the trust level for a (task_class × domain × model) triple.

    Returns: int (0-4), higher = more autonomy
    """
    task_class = task.get("kind", "feature")
    key = _trust_key(task_class, domain, agent_id)
    data = _trust_data()
    entry = data.get(key, {})

    merges = entry.get("merges", 0)
    total = entry.get("total", 0)
    rollbacks = entry.get("rollbacks", 0)

    if total == 0:
        return 0

    merge_rate = merges / total

    for min_merges, min_rate, max_rolls, level in LEVELS:
        if merges >= min_merges and merge_rate >= min_rate and rollbacks <= max_rolls:
            return level

    return 0


def gates_to_skip(level):
    """Return which gates can be skipped at this trust level.

    Returns: {skip_judge, skip_verify, skip_build, skip_confidence, skip_all}
    """
    return {
        "skip_judge": level >= 1,
        "skip_verify": level >= 2,
        "skip_build": level >= 3,
        "skip_confidence": level >= 3,
        "skip_all": level >= 4,
        "level": level,
    }


def record_outcome(task, agent_id="", domain="backend", merged=False, rollback=False):
    """Record an outcome and update trust level.

    A rollback resets to Level 0 immediately.
    """
    task_class = task.get("kind", "feature")
    key = _trust_key(task_class, domain, agent_id)
    data = _trust_data()

    entry = data.get(key, {
        "task_class": task_class, "domain": domain, "agent_id": agent_id,
        "merges": 0, "total": 0, "rollbacks": 0,
        "consecutive_merges": 0, "level": 0,
    })

    entry["total"] = entry.get("total", 0) + 1

    if rollback:
        # Immediate reset to Level 0
        entry["rollbacks"] = entry.get("rollbacks", 0) + 1
        entry["consecutive_merges"] = 0
        entry["level"] = 0
    elif merged:
        entry["merges"] = entry.get("merges", 0) + 1
        entry["consecutive_merges"] = entry.get("consecutive_merges", 0) + 1
    else:
        entry["consecutive_merges"] = 0

    # Recompute level
    merges = entry["merges"]
    total = entry["total"]
    rollbacks = entry["rollbacks"]
    merge_rate = merges / total if total > 0 else 0

    computed_level = 0
    for min_merges, min_rate, max_rolls, lvl in LEVELS:
        if merges >= min_merges and merge_rate >= min_rate and rollbacks <= max_rolls:
            computed_level = lvl
            break

    entry["level"] = computed_level
    entry["merge_rate"] = round(merge_rate, 3)
    entry["last_updated"] = time.time()

    data[key] = entry
    _save_trust(data)
    return entry


def should_skip_gates(task, agent_id="", domain="backend"):
    """Quick check: what gates should be skipped for this task?

    Returns (gates_config: dict, level: int)
    """
    level = trust_level(task, agent_id, domain)
    return gates_to_skip(level), level


def run():
    """Periodic: log trust levels and level distribution."""
    data = _trust_data()
    if not data:
        print("[graduated-autonomy] no trust data yet")
        return

    levels = [v.get("level", 0) for v in data.values()]
    dist = {i: levels.count(i) for i in range(5)}
    high_trust = sum(1 for l in levels if l >= 3)

    print(f"[graduated-autonomy] {len(data)} triples | "
          f"L0={dist.get(0,0)} L1={dist.get(1,0)} L2={dist.get(2,0)} "
          f"L3={dist.get(3,0)} L4={dist.get(4,0)} | "
          f"{high_trust} at high trust")
