#!/usr/bin/env python3
"""
cheap_worker.py — lightweight task worker for low-cost model routing.

Handles tasks that can be completed by cheap/local models (Ollama, small
API models) without burning expensive API credits. Claims tasks with
force_coder set to cheap providers and routes them to the appropriate
local or low-cost model endpoint.

Env vars:
    ORCH_CHEAP_WORKER_ENABLED   "true" to enable (default "true")
    ORCH_CHEAP_MODELS           comma-separated list of cheap model prefixes
    ORCH_CHEAP_TIMEOUT_S        timeout per task in seconds (default 300)
    ORCH_CHEAP_MAX_PARALLEL     max concurrent cheap tasks (default 2)
"""
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_CHEAP_WORKER_ENABLED", "true").lower() in ("1", "true", "yes")
CHEAP_MODELS = [m.strip() for m in os.environ.get(
    "ORCH_CHEAP_MODELS", "ollama,local,deepseek").split(",") if m.strip()]
TIMEOUT_S = int(os.environ.get("ORCH_CHEAP_TIMEOUT_S", "300"))
MAX_PARALLEL = int(os.environ.get("ORCH_CHEAP_MAX_PARALLEL", "2"))


_lock = threading.Lock()
_stats = {"claimed": 0, "completed": 0, "failed": 0, "skipped": 0}


def stats():
    with _lock:
        return dict(_stats)


def is_cheap_model(model_name):
    """Return True if model_name matches a cheap/local provider."""
    if not model_name:
        return False
    lower = model_name.lower()
    return any(lower.startswith(prefix) for prefix in CHEAP_MODELS)


def claim_cheap_tasks(batch_size=None):
    """Claim tasks routed to cheap models. Returns list of task dicts."""
    if not ENABLED:
        return []
    batch_size = batch_size or MAX_PARALLEL
    try:
        import db
        rows = db.select("tasks", {
            "select": "id,slug,project_id,prompt,kind,attempt,force_coder",
            "state": "eq.QUEUED",
            "order": "attempt.asc,id.asc",
            "limit": str(batch_size),
        }) or []
    except Exception:
        return []

    cheap = [r for r in rows if is_cheap_model(r.get("force_coder", ""))]
    return cheap


def execute_task(task):
    """Execute a single cheap task. Returns result dict.

    Currently a stub — routes to the appropriate model endpoint.
    The actual model invocation is handled by agentic_coders.py;
    this module handles the claim/routing layer.
    """
    slug = task.get("slug", "unknown")
    model = task.get("force_coder", "unknown")

    with _lock:
        _stats["claimed"] += 1

    try:
        # Route to model — in production, this calls the local Ollama
        # endpoint or a cheap API model via agentic_coders
        result = {
            "slug": slug,
            "model": model,
            "status": "routed",
            "timeout_s": TIMEOUT_S,
        }
        with _lock:
            _stats["completed"] += 1
        return result
    except Exception as e:
        with _lock:
            _stats["failed"] += 1
        return {"slug": slug, "error": str(e), "status": "failed"}


def run():
    """CLI entry point — report available cheap tasks."""
    if not ENABLED:
        print("cheap_worker: disabled")
        return {}
    tasks = claim_cheap_tasks()
    print(f"cheap_worker: {len(tasks)} task(s) available for cheap models")
    for t in tasks[:5]:
        print(f"  {t.get('slug', '?')} -> {t.get('force_coder', '?')}")
    return {"available": len(tasks), "stats": stats()}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
