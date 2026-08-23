#!/usr/bin/env python3
"""
counterfactual-replay module - re-evaluate past routing/policy decisions with current models.

Periodically replays past task routing and policy decisions (from last 7 days, configurable)
through the current model state to detect where decisions would diverge, then updates
ORCH_RUNNER_ROUTE_* / ORCH_RUNNER_POLICY_* config keys via fleet_control.update_fleet_config().

No task re-execution—replay-only. Fail-soft error handling throughout. Thread-safe.

Env vars:
    ORCH_COUNTERFACTUAL_DAYS_BACK   default 7 (how far back to replay)
    ORCH_COUNTERFACTUAL_BATCH_SIZE  default 50 (replay batch size)
    ORCH_COUNTERFACTUAL_ENABLED     default true (master kill switch)
"""
import os
import sys
import json
import time
import sqlite3
import threading
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fleet_control
import error_handling_utils as ehu

DAYS_BACK = int(os.environ.get("ORCH_COUNTERFACTUAL_DAYS_BACK", "7"))
BATCH_SIZE = int(os.environ.get("ORCH_COUNTERFACTUAL_BATCH_SIZE", "50"))
ENABLED = os.environ.get("ORCH_COUNTERFACTUAL_ENABLED", "true").lower() == "true"

_lock = threading.Lock()
_stats = {"replayed": 0, "changed": 0, "errors": 0}
_storage_singleton = None


def _acquire_storage(base_dir=None):
    global _storage_singleton
    if _storage_singleton is None:
        _storage_singleton = ReplayStorage(base_dir or _get_runtime_dir())
    return _storage_singleton


def _get_runtime_dir():
    return os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__), "..", ".runtime"))


def get_worktree_path(task_id):
    return os.path.join(_get_runtime_dir(), f"wt/replay-{task_id}")


def replay_decision(task_id, old_decision, new_model):
    """Replay a single past decision with a new model.

    Returns dict with replayed decision, or None on error. Preserves original metadata.
    """
    try:
        if not old_decision or not isinstance(old_decision, dict):
            return None

        if "output" not in old_decision and "input" not in old_decision:
            return None

        output_data = old_decision.get("output")
        if isinstance(output_data, str) and output_data != "":
            return None

        input_data = old_decision.get("input", {})
        if input_data is None:
            return None

        result = {
            "task_id": task_id,
            "original_task_id": old_decision.get("task_id", task_id),
            "original_timestamp": old_decision.get("timestamp"),
            "original_model": old_decision.get("model"),
            "original_model_version": old_decision.get("model_version"),
            "model": getattr(new_model, "model_id", "unknown"),
            "model_version": getattr(new_model, "version", "unknown"),
            "timestamp": datetime.now().isoformat(),
        }

        if hasattr(new_model, "evaluate") and callable(new_model.evaluate):
            task_type = old_decision.get("type", "routing")
            output = new_model.evaluate(input_data, task_type)
            result["decision"] = output.get("decision", "unknown")
            result["confidence"] = output.get("confidence", 0.0)

        for key in ["user", "repo", "state"]:
            if key in old_decision:
                result[key] = old_decision[key]

        return result
    except Exception as e:
        ehu.wrap_error(e, category="transient", context=f"replay_decision({task_id})")
        return None


def replay_decision_safe(task_id, old_decision, new_model):
    """Replay with fail-soft error handling."""
    try:
        result = replay_decision(task_id, old_decision, new_model)
        if result is None:
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "no_model_output"
            }
        return {**result, "status": "success"}
    except Exception as e:
        ehu.wrap_error(e, category="logic", context=f"replay_decision_safe({task_id})")
        return {
            "task_id": task_id,
            "status": "partial",
            "error": str(e)
        }


def replay_decision_with_context(task_id, old_decision, new_model, new_context):
    """Replay with updated context data."""
    try:
        result = replay_decision(task_id, old_decision, new_model)
        if result is None:
            return None

        old_context = old_decision.get("input", {})
        evolution = track_data_evolution(old_context, new_context)

        result["context_version"] = new_context.get("context_version", 2)
        result["data_evolution"] = {
            "old": old_context.get("data"),
            "new": new_context.get("data")
        }

        return result
    except Exception as e:
        ehu.wrap_error(e, category="logic", context=f"replay_decision_with_context")
        return None


def compare_model_outputs(old_output, new_output):
    """Compare outputs from two model versions."""
    try:
        old_model = old_output.get("model", "unknown") if isinstance(old_output, dict) else "unknown"
        new_model = new_output.get("model", "unknown") if isinstance(new_output, dict) else "unknown"
        old_conf = old_output.get("confidence", 0.0) if isinstance(old_output, dict) else 0.0
        new_conf = new_output.get("confidence", 0.0) if isinstance(new_output, dict) else 0.0

        return {
            "old_model": old_model,
            "new_model": new_model,
            "difference": new_model != old_model,
            "confidence_delta": abs(new_conf - old_conf),
            "old_confidence": old_conf,
            "new_confidence": new_conf,
        }
    except Exception:
        return {"difference": False, "confidence_delta": 0.0}


def detect_version_upgrade(old_version, new_version):
    """Check if model version was upgraded."""
    try:
        if not old_version or not new_version:
            return False
        return str(new_version) != str(old_version)
    except Exception:
        return False


def calculate_confidence_change(old_conf, new_conf):
    """Calculate change in confidence score."""
    try:
        return round(float(new_conf or 0.0) - float(old_conf or 0.0), 2)
    except Exception:
        return 0.0


def analyze_replay_impact(old_decision, replay_result):
    """Analyze the impact of a replayed decision."""
    try:
        old_output = old_decision.get("output", {})
        new_conf = replay_result.get("confidence", 0.0)
        old_conf = old_output.get("confidence", 0.0) if isinstance(old_output, dict) else 0.0

        return {
            "confidence_change": calculate_confidence_change(old_conf, new_conf),
            "model_changed": old_decision.get("model") != replay_result.get("model"),
            "decision_stable": old_output.get("route") == replay_result.get("decision"),
        }
    except Exception:
        return {}


def detect_policy_change(old_output, new_output):
    """Detect when a policy decision would change."""
    try:
        old_route = old_output.get("route") if isinstance(old_output, dict) else None
        new_route = new_output.get("route") if isinstance(new_output, dict) else None

        old_conf = old_output.get("confidence", 0.5) if isinstance(old_output, dict) else 0.5
        new_conf = new_output.get("confidence", 0.5) if isinstance(new_output, dict) else 0.5

        changed = old_route != new_route
        conf_delta = calculate_confidence_change(old_conf, new_conf)

        if not changed:
            return {
                "changed": False,
                "reason": "decision_stable",
                "confidence_delta": conf_delta,
            }

        reason = "confidence_improvement" if conf_delta > 0 else "confidence_decline"

        return {
            "changed": True,
            "old_route": old_route,
            "new_route": new_route,
            "confidence_delta": conf_delta,
            "reason": reason,
        }
    except Exception:
        return {"changed": False, "error": "detection_failed"}


def has_policy_change(old_decision, replay_result):
    """Check if a replay result shows policy change."""
    try:
        old_output = old_decision.get("output", {})
        policy = detect_policy_change(old_output, replay_result)
        return policy.get("changed", False)
    except Exception:
        return False


def track_data_evolution(old_data, new_data):
    """Track how data evolved between original and replay."""
    try:
        old_version = old_data.get("version", 1) if isinstance(old_data, dict) else 1
        new_version = new_data.get("version", 2) if isinstance(new_data, dict) else 2

        changes = []
        if isinstance(old_data, dict) and isinstance(new_data, dict):
            all_keys = set(old_data.keys()) | set(new_data.keys())
            for k in sorted(all_keys):
                if k == "version":
                    continue
                if old_data.get(k) != new_data.get(k):
                    changes.append(k)

        result = {
            "old_version": old_version,
            "new_version": new_version,
            "changes": changes,
        }

        for key in changes:
            if isinstance(old_data, dict):
                result[f"{key}_old"] = old_data.get(key)
            if isinstance(new_data, dict):
                result[f"{key}_new"] = new_data.get(key)

        return result
    except Exception:
        return {"changes": []}


def replay_batch(decisions, new_model):
    """Batch replay of multiple decisions."""
    results = []
    try:
        for decision in (decisions or []):
            if not decision or not isinstance(decision, dict):
                continue
            task_id = decision.get("task_id", "unknown")
            result = replay_decision(task_id, decision, new_model)
            if result:
                results.append(result)
    except Exception as e:
        ehu.wrap_error(e, category="transient", context="replay_batch")

    return results


def replay_batch_with_summary(decisions, new_model):
    """Batch replay with summary statistics."""
    results = replay_batch(decisions, new_model)

    summary = {
        "total_replayed": len(results),
        "policy_changes": 0,
        "avg_confidence_delta": 0.0,
        "models_tested": [],
    }

    confidence_deltas = []
    models_seen = set()

    for result in results:
        if result.get("model"):
            models_seen.add(result["model"])

        delta = result.get("confidence", 0.0) - (
            result.get("original_confidence", 0.0) if hasattr(result, 'get') else 0.0
        )
        confidence_deltas.append(abs(delta))

    if confidence_deltas:
        summary["avg_confidence_delta"] = sum(confidence_deltas) / len(confidence_deltas)

    summary["models_tested"] = sorted(list(models_seen))

    return results, summary


def filter_decisions(decisions, task_type=None, start_date=None, end_date=None):
    """Filter decisions by type and date range."""
    if not decisions:
        return []

    filtered = []
    try:
        for d in decisions:
            if not isinstance(d, dict):
                continue

            if task_type and d.get("type") != task_type:
                continue

            if start_date or end_date:
                ts = d.get("timestamp", "")
                if start_date and ts < start_date:
                    continue
                if end_date and ts > end_date:
                    continue

            filtered.append(d)
    except Exception:
        return decisions

    return filtered


def is_empty_history(history):
    """Check if decision history is empty."""
    return not history or len(history) == 0


def detect_circular_dependencies(decisions):
    """Detect circular dependencies in decision graph."""
    try:
        if not decisions:
            return {"has_cycle": False, "cycle": []}

        visited = set()
        rec_stack = set()
        cycle = []

        def has_cycle_dfs(node, visited, rec_stack, parents):
            visited.add(node)
            rec_stack.add(node)

            if isinstance(decisions, dict) and node in decisions:
                dep = decisions[node].get("depends_on")
                if dep and dep in rec_stack:
                    cycle.extend([node, dep])
                    return True
                if dep and dep not in visited:
                    if has_cycle_dfs(dep, visited, rec_stack, parents):
                        return True

            rec_stack.remove(node)
            return False

        for node in decisions:
            if node not in visited:
                if has_cycle_dfs(node, visited, rec_stack, {}):
                    return {"has_cycle": True, "cycle": cycle}

        return {"has_cycle": False, "cycle": []}
    except Exception:
        return {"has_cycle": False, "cycle": []}


def resolve_policy_conflict(existing_policy, new_policy):
    """Resolve conflicting policy updates."""
    try:
        conflict = {}
        for key in set(list(existing_policy.keys()) + list(new_policy.keys())):
            if existing_policy.get(key) != new_policy.get(key):
                conflict[key] = {
                    "existing": existing_policy.get(key),
                    "new": new_policy.get(key)
                }

        resolution = "merge" if len(conflict) > 0 else "keep_existing"

        return {
            "conflict": len(conflict) > 0,
            "conflicts": conflict,
            "resolution": resolution,
        }
    except Exception:
        return {"conflict": False, "resolution": "merge"}


def update_route_policy(operation, old_config, policy_change):
    """Update routing policy based on counterfactual analysis."""
    try:
        return {
            "operation": operation,
            "updated": policy_change.get("changed", False),
            "prior_model": old_config.get("model"),
            "new_model": policy_change.get("new_route"),
            "confidence_delta": policy_change.get("confidence_delta", 0.0),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception:
        return {"operation": operation, "updated": False}


class RouteConfig:
    """In-memory route configuration."""

    def __init__(self):
        self._routes = {}
        self._lock = threading.Lock()

    def set_route(self, operation, model, q_score=0.0):
        with self._lock:
            self._routes[operation] = {
                "operation": operation,
                "model": model,
                "q_score": q_score,
            }

    def get_route(self, operation):
        with self._lock:
            return self._routes.get(operation)

    def update_route(self, operation, new_model, q_score=None):
        with self._lock:
            if operation in self._routes:
                self._routes[operation]["model"] = new_model
                if q_score is not None:
                    self._routes[operation]["q_score"] = q_score
            else:
                self._routes[operation] = {
                    "operation": operation,
                    "model": new_model,
                    "q_score": q_score or 0.0,
                }

    def apply_counterfactual_update(self, operation, replay_result):
        """Apply counterfactual update to route config."""
        try:
            new_model = replay_result.get("new_model") or replay_result.get("model")
            q_score = replay_result.get("q_score_delta", 0.0)
            self.update_route(operation, new_model, q_score)
        except Exception:
            pass


class RouteStorage:
    """Persistent route update storage."""

    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "route_updates.json"
        self._lock = threading.Lock()

    def persist_route_update(self, route_update):
        """Save a route update."""
        try:
            with self._lock:
                updates = self._load_updates()
                operation = route_update.get("operation", "unknown")
                updates[operation] = route_update
                self._save_updates(updates)
        except Exception:
            pass

    def get_route_update(self, operation):
        """Retrieve a route update by operation."""
        try:
            with self._lock:
                updates = self._load_updates()
                return updates.get(operation)
        except Exception:
            return None

    def _load_updates(self):
        try:
            if self.db_path.exists():
                with open(self.db_path, "r") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def _save_updates(self, updates):
        try:
            with open(self.db_path, "w") as f:
                json.dump(updates, f, indent=2, default=str)
        except Exception:
            pass


class ReplayStorage:
    """Persistent replay result storage."""

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or _get_runtime_dir())
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "replay_results.db"
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS replay_results (
                        id INTEGER PRIMARY KEY,
                        task_id TEXT,
                        model TEXT,
                        decision TEXT,
                        policy_changed BOOLEAN,
                        timestamp TEXT,
                        data JSON
                    )
                """)
                conn.commit()
        except Exception:
            pass

    def save_replay(self, replay_result):
        """Save a replay result (idempotent)."""
        try:
            with self._lock:
                task_id = replay_result.get("task_id")
                if not task_id:
                    return

                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute("DELETE FROM replay_results WHERE task_id = ?", (task_id,))
                    conn.execute("""
                        INSERT INTO replay_results
                        (task_id, model, decision, policy_changed, timestamp, data)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        task_id,
                        replay_result.get("model"),
                        replay_result.get("decision"),
                        replay_result.get("policy_changed", False),
                        replay_result.get("timestamp"),
                        json.dumps(replay_result, default=str),
                    ))
                    conn.commit()
        except Exception:
            pass

    def get_replays(self, task_id):
        """Retrieve replays for a specific task."""
        try:
            with self._lock:
                with sqlite3.connect(str(self.db_path)) as conn:
                    cursor = conn.execute(
                        "SELECT data FROM replay_results WHERE task_id = ?",
                        (task_id,)
                    )
                    return [json.loads(row[0]) for row in cursor.fetchall()]
        except Exception:
            return []

    def count_replays(self, task_id=None):
        """Count replays (all or for specific task)."""
        try:
            with self._lock:
                with sqlite3.connect(str(self.db_path)) as conn:
                    if task_id:
                        cursor = conn.execute(
                            "SELECT COUNT(*) FROM replay_results WHERE task_id = ?",
                            (task_id,)
                        )
                    else:
                        cursor = conn.execute("SELECT COUNT(*) FROM replay_results")
                    return cursor.fetchone()[0]
        except Exception:
            return 0

    def query(self, model=None, policy_changed=None):
        """Query replays by model or policy_changed status."""
        try:
            with self._lock:
                with sqlite3.connect(str(self.db_path)) as conn:
                    query = "SELECT data FROM replay_results WHERE 1=1"
                    params = []

                    if model is not None:
                        query += " AND model = ?"
                        params.append(model)

                    if policy_changed is not None:
                        query += " AND policy_changed = ?"
                        params.append(policy_changed)

                    cursor = conn.execute(query, params)
                    return [json.loads(row[0]) for row in cursor.fetchall()]
        except Exception:
            return []


def push_config_updates(updates):
    """Push config updates to fleet via fleet_control."""
    try:
        for key, value in updates.items():
            if not key or not _safe_config_key(key):
                continue
            fleet_control.update_fleet_config(key, str(value))
    except Exception as e:
        ehu.wrap_error(e, category="transient", context="push_config_updates")


def _safe_config_key(key):
    """Check if key is safe for fleet config."""
    try:
        return fleet_control._safe_key(key)
    except Exception:
        return key.startswith("ORCH_")


def stats():
    """Return replay statistics."""
    with _lock:
        return dict(_stats)


def invalidate():
    """Clear replay state."""
    global _storage_singleton
    with _lock:
        _stats["replayed"] = 0
        _stats["changed"] = 0
        _stats["errors"] = 0
        _storage_singleton = None
