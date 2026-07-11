"""
queue_preopt.py — Queue Pre-Optimization System.

Background daemon that pre-processes QUEUED tasks while they wait, so when a runner
claims them, expensive hook computations are already cached and execution starts faster.

Pre-computes:
  - context_pack: repo map + conventions block
  - precedent: most-similar merged change
  - unified_knowledge: cross-store knowledge matches
  - ensemble_predictor: failure prediction
  - output_recycling: partial work from prior attempts
  - ai_review: cheap-model (haiku) spec review for completeness

Usage:
  # In runner.py main loop, start the background daemon:
  import queue_preopt
  queue_preopt.start()

  # In run_task(), check for pre-computed results:
  cached = queue_preopt.get(task_id)
  if cached:
      _extras = cached.get("context_pack", "")
      # ... skip expensive re-computation

  # When a task is claimed or state changes:
  queue_preopt.invalidate(task_id)

The daemon is intentionally low-priority: it yields to active task execution and
throttles itself based on system load.
"""

import os
import sys
import time
import json
import threading
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("queue_preopt")

# ── Configuration ──────────────────────────────────────────────────────────────

# How often the daemon scans for idle QUEUED tasks (seconds)
SCAN_INTERVAL = float(os.environ.get("ORCH_PREOPT_SCAN_INTERVAL", "30"))

# Max tasks to pre-optimize per scan cycle
MAX_PER_CYCLE = int(os.environ.get("ORCH_PREOPT_MAX_PER_CYCLE", "5"))

# TTL for cached pre-optimizations (seconds) — re-compute if stale
CACHE_TTL = float(os.environ.get("ORCH_PREOPT_CACHE_TTL", "300"))

# Skip pre-opt when system load exceeds this (0.0-1.0)
LOAD_CEILING = float(os.environ.get("ORCH_PREOPT_LOAD_CEILING", "0.85"))

# Enable/disable the daemon entirely
ENABLED = os.environ.get("ORCH_PREOPT_ENABLED", "true").lower() in ("true", "1", "yes")

# Enable AI review of queued task specs (uses cheap model, costs tokens)
AI_REVIEW_ENABLED = os.environ.get("ORCH_PREOPT_AI_REVIEW", "true").lower() in ("true", "1", "yes")

AI_REVIEW_MODEL = os.environ.get("ORCH_PREOPT_AI_MODEL", "claude-haiku-4-5-20251001")


# ── Cache ──────────────────────────────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache = {}  # task_id -> {"ts": float, "data": dict, "task_hash": str}

_daemon_thread = None
_stop_event = threading.Event()


def get(task_id):
    """Retrieve pre-computed results for a task. Returns None if no cache or expired."""
    with _cache_lock:
        entry = _cache.get(task_id)
    if not entry:
        return None
    if time.time() - entry["ts"] > CACHE_TTL:
        invalidate(task_id)
        return None
    return entry["data"]


def invalidate(task_id):
    """Remove cached pre-optimization for a task (e.g. when claimed or modified)."""
    with _cache_lock:
        _cache.pop(task_id, None)


def invalidate_all():
    """Clear the entire pre-optimization cache."""
    with _cache_lock:
        _cache.clear()


def stats():
    """Return cache statistics for monitoring."""
    with _cache_lock:
        cached_ids = list(_cache.keys())
        now = time.time()
        fresh = sum(1 for e in _cache.values() if now - e["ts"] < CACHE_TTL)
    return {
        "cached_tasks": len(cached_ids),
        "fresh": fresh,
        "stale": len(cached_ids) - fresh,
        "enabled": ENABLED,
        "daemon_alive": _daemon_thread is not None and _daemon_thread.is_alive(),
    }


def start():
    """Start the background pre-optimization daemon. Idempotent."""
    global _daemon_thread
    if not ENABLED:
        _log.info("queue pre-optimization disabled (ORCH_PREOPT_ENABLED=false)")
        return
    if _daemon_thread is not None and _daemon_thread.is_alive():
        return
    _stop_event.clear()
    _daemon_thread = threading.Thread(target=_daemon_loop, daemon=True, name="queue-preopt")
    _daemon_thread.start()
    _log.info("queue pre-optimization daemon started (interval=%ss, max_per_cycle=%d)",
              SCAN_INTERVAL, MAX_PER_CYCLE)


def stop():
    """Stop the background daemon."""
    _stop_event.set()
    if _daemon_thread is not None:
        _daemon_thread.join(timeout=10)
    _log.info("queue pre-optimization daemon stopped")


# ── Daemon Loop ────────────────────────────────────────────────────────────────

def _daemon_loop():
    """Main daemon loop: scan QUEUED tasks, pre-optimize uncached ones."""
    while not _stop_event.is_set():
        try:
            _scan_and_preopt()
        except Exception as e:
            _log.debug("preopt scan cycle failed: %s", e)
        _stop_event.wait(SCAN_INTERVAL)


def _scan_and_preopt():
    """One scan cycle: find QUEUED tasks, pre-optimize up to MAX_PER_CYCLE."""
    # Check system load — don't compete with active task execution
    if not _system_has_capacity():
        return

    import db

    # Fetch QUEUED tasks ordered by priority (same ordering as claim_task)
    queued = db.select("tasks", {
        "select": "id,slug,project_id,deps,kind,prompt,note,created_at,confidence",
        "state": "eq.QUEUED",
        "order": "created_at.asc",
        "limit": str(MAX_PER_CYCLE * 3),  # fetch more, filter to uncached
    }) or []

    if not queued:
        return

    # Filter to tasks not already cached (or stale)
    now = time.time()
    to_process = []
    for t in queued:
        tid = t.get("id")
        if not tid:
            continue
        with _cache_lock:
            entry = _cache.get(tid)
        if entry and now - entry["ts"] < CACHE_TTL:
            # Check if task changed since cached (prompt/note hash)
            current_hash = _task_hash(t)
            if entry.get("task_hash") == current_hash:
                continue  # still fresh and unchanged
        to_process.append(t)
        if len(to_process) >= MAX_PER_CYCLE:
            break

    if not to_process:
        return

    # Get project info for repo paths
    projects = {}
    try:
        projs = db.select("projects", {"select": "id,name,repo_path"}) or []
        projects = {p["id"]: p for p in projs}
    except Exception:
        pass

    for t in to_process:
        if _stop_event.is_set():
            break
        try:
            result = _preopt_task(t, projects)
            if result:
                _store(t["id"], result, _task_hash(t))
                _log.debug("pre-optimized task %s (%s)", t["id"], t.get("slug", "?"))
        except Exception as e:
            _log.debug("preopt for task %s failed: %s", t.get("id"), e)


def _preopt_task(t, projects):
    """Pre-compute expensive hook results for a single QUEUED task."""
    result = {"preopt_at": time.time(), "stages": []}
    tid = t.get("id")
    pid = t.get("project_id")
    proj = projects.get(pid, {})
    repo = proj.get("repo_path", "")
    name = proj.get("name", "")

    # Localize repo path for this machine
    try:
        import db as _db
        repo = _db.localize_repo_path(repo) if hasattr(_db, "localize_repo_path") else repo
    except Exception:
        pass

    if not repo or not os.path.isdir(repo):
        return result  # can't pre-optimize without a repo

    # Stage 1: Context pack (repo map + conventions)
    try:
        import context_pack
        result["context_pack"] = context_pack.block(repo)
        result["stages"].append("context_pack")
    except Exception as e:
        _log.debug("preopt context_pack failed for %s: %s", tid, e)

    # Stage 2: Precedent hint (most-similar merged change)
    try:
        import precedent
        result["precedent_hint"] = precedent.hint(t, repo, project_id=pid)
        result["stages"].append("precedent")
    except Exception as e:
        _log.debug("preopt precedent failed for %s: %s", tid, e)

    # Stage 3: Unified knowledge query
    try:
        import unified_knowledge
        uk = unified_knowledge.query(t, name, repo, attempt=0)
        if uk and uk.get("matches"):
            result["unified_knowledge"] = uk
            result["stages"].append("unified_knowledge")
    except Exception as e:
        _log.debug("preopt unified_knowledge failed for %s: %s", tid, e)

    # Stage 4: Ensemble failure prediction
    try:
        import ensemble_predictor, model_portfolios
        _domain = "backend"
        try:
            _domain = model_portfolios.classify(t, [])
        except Exception:
            pass
        ens = ensemble_predictor.predict(t, "claude:claude-sonnet-4-6", _domain, "claude-sonnet-4-6")
        if ens:
            result["ensemble_prediction"] = ens
            result["stages"].append("ensemble_prediction")
    except Exception as e:
        _log.debug("preopt ensemble_predictor failed for %s: %s", tid, e)

    # Stage 5: Output recycling (prior attempt partial work)
    try:
        import output_recycling
        recycled = output_recycling.get_recycled(tid)
        if recycled:
            result["recycled_output"] = recycled
            result["stages"].append("output_recycling")
    except Exception as e:
        _log.debug("preopt output_recycling failed for %s: %s", tid, e)

    # Stage 6: Transfer learning query
    try:
        import transfer_learning
        transfer = transfer_learning.find_transfer(t, current_project=name)
        if transfer:
            result["transfer_learning"] = transfer
            result["stages"].append("transfer_learning")
    except Exception as e:
        _log.debug("preopt transfer_learning failed for %s: %s", tid, e)

    # Stage 7: Prompt distillation lookup
    try:
        import prompt_distillation
        distilled = prompt_distillation.find_distilled(t, current_project=name)
        if distilled:
            result["prompt_distillation"] = distilled
            result["stages"].append("prompt_distillation")
    except Exception as e:
        _log.debug("preopt prompt_distillation failed for %s: %s", tid, e)

    # Stage 8: AI spec review (cheap model reviews task for completeness/issues)
    if AI_REVIEW_ENABLED:
        try:
            ai_review = _ai_review_task(t, repo, name)
            if ai_review:
                result["ai_review"] = ai_review
                result["stages"].append("ai_review")
        except Exception as e:
            _log.debug("preopt ai_review failed for %s: %s", tid, e)

    return result


def _ai_review_task(t, repo, project_name):
    """Have a cheap model review the task spec for completeness, ambiguity, and issues.
    Returns structured review or None."""
    prompt_text = t.get("prompt") or t.get("slug") or ""
    if not prompt_text or len(prompt_text) < 20:
        return None

    review_prompt = f"""You are a pre-flight reviewer for an automated coding system. Review this task
spec and return a JSON object with:
- "issues": list of potential problems (missing context, ambiguous scope, conflicting requirements)
- "suggestions": list of improvements that would help the coding agent succeed on first pass
- "estimated_complexity": "trivial"|"simple"|"moderate"|"complex"|"very_complex"
- "recommended_model": "haiku"|"sonnet"|"opus" (based on complexity)
- "missing_context": list of files or context the agent will likely need
- "merge_risk": "low"|"medium"|"high" with brief reason

Project: {project_name}
Task slug: {t.get('slug', 'unknown')}
Task kind: {t.get('kind', 'unknown')}

Task spec:
{prompt_text[:4000]}

Return ONLY valid JSON, no markdown fences."""

    try:
        import claude_cli
        r = claude_cli.run(review_prompt, AI_REVIEW_MODEL, timeout=120)
        import re
        m = re.search(r"\{.*\}", r.get("text", ""), re.S)
        if m:
            review = json.loads(m.group(0))
            review["model_used"] = AI_REVIEW_MODEL
            review["tokens"] = {
                "input": r.get("input_tokens", 0),
                "output": r.get("output_tokens", 0),
            }
            return review
    except Exception as e:
        _log.debug("ai_review model call failed: %s", e)
    return None


# ── Integration: runner.py hooks into these ────────────────────────────────────

def apply_cached(task_id, draft_prompt, t, repo, name, attempt):
    """Apply pre-computed results to a task being executed. Returns (modified_prompt, extras, notes).
    Call this early in run_task() to skip redundant hook computations."""
    cached = get(task_id)
    if not cached:
        return draft_prompt, "", []

    notes = []
    extras = ""

    # Apply context pack
    if cached.get("context_pack"):
        extras += cached["context_pack"]
        notes.append("preopt:context_pack")

    # Apply precedent hint
    if cached.get("precedent_hint"):
        extras += cached["precedent_hint"]
        notes.append("preopt:precedent")

    # Apply unified knowledge matches
    uk = cached.get("unified_knowledge")
    if uk and uk.get("matches"):
        try:
            import unified_knowledge as _uk_mod
            draft_prompt = _uk_mod._apply_match(draft_prompt, uk["matches"][0])
            notes.append(f"preopt:unified_knowledge ({len(uk['matches'])} matches)")
        except Exception:
            pass

    # Apply recycled output
    if cached.get("recycled_output"):
        try:
            import output_recycling
            draft_prompt = output_recycling.inject_recycled(draft_prompt, cached["recycled_output"])
            notes.append("preopt:output_recycling")
        except Exception:
            pass

    # Apply transfer learning
    if cached.get("transfer_learning"):
        try:
            import transfer_learning
            draft_prompt = transfer_learning.inject_transfer(draft_prompt, cached["transfer_learning"])
            notes.append(f"preopt:transfer_learning ({cached['transfer_learning'].get('source_project', '?')})")
        except Exception:
            pass

    # Apply prompt distillation
    if cached.get("prompt_distillation"):
        try:
            import prompt_distillation
            draft_prompt = prompt_distillation.apply_distilled(draft_prompt, cached["prompt_distillation"])
            notes.append("preopt:prompt_distillation")
        except Exception:
            pass

    # Log AI review insights (advisory, doesn't change prompt)
    ai = cached.get("ai_review")
    if ai:
        issues = ai.get("issues", [])
        if issues:
            notes.append(f"preopt:ai_review ({len(issues)} issues, risk={ai.get('merge_risk', '?')})")

    # Invalidate now that we've consumed the cache
    invalidate(task_id)

    return draft_prompt, extras, notes


# ── Helpers ────────────────────────────────────────────────────────────────────

def _task_hash(t):
    """Hash task fields that matter for cache invalidation."""
    key = json.dumps({
        "slug": t.get("slug"),
        "prompt": (t.get("prompt") or "")[:500],
        "note": t.get("note"),
        "kind": t.get("kind"),
    }, sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _store(task_id, data, task_hash):
    """Store pre-optimization result in cache."""
    with _cache_lock:
        _cache[task_id] = {
            "ts": time.time(),
            "data": data,
            "task_hash": task_hash,
        }


def _system_has_capacity():
    """Check if the system has spare capacity for pre-optimization work."""
    try:
        import resource_governor
        if hasattr(resource_governor, "can_claim") and not resource_governor.can_claim():
            return False
    except Exception:
        pass

    # Check active task count vs capacity
    try:
        import db
        active = db.select("tasks", {
            "select": "id",
            "state": "in.(RUNNING,RETRY)",
            "limit": "50",
        }) or []
        max_parallel = int(os.environ.get("MAX_PARALLEL", "10"))
        # Only pre-opt when less than LOAD_CEILING of capacity is in use
        if len(active) >= int(max_parallel * LOAD_CEILING):
            return False
    except Exception:
        pass  # fail open — allow pre-opt if we can't check

    return True
