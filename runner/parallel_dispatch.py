#!/usr/bin/env python3
"""
parallel_dispatch.py — Batch-parallel swarm dispatch for API-eligible tasks.

Instead of the runner claiming one task at a time (claim → thread → loop), this
module claims a batch of tasks in one go and dispatches API-eligible ones through
swarm_executor concurrently, falling back to _run_task_safe for CLI-only tasks.

Usage (from runner.py main loop):
    import parallel_dispatch

    if parallel_dispatch.should_use_swarm(eff_limit, len(active)):
        stats = parallel_dispatch.dispatch_swarm_batch(RUNNER_ID, active)

Env:
    ORCH_SWARM_DISPATCH       "true" to enable (default "true")
    ORCH_SWARM_BATCH_SIZE     max tasks to claim per batch (default 10)
    ORCH_SWARM_HOURLY_CAP     hourly USD ceiling for swarm dispatch (default 15)
    ORCH_SWARM_MIN_QUEUED     minimum queued tasks to justify batch overhead (default 5)
"""
import os, sys, time, logging, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (all env-tunable, hot-reloaded each call)
# ---------------------------------------------------------------------------
_DISPATCH_DEFAULT = "true"
_BATCH_DEFAULT = "10"
_HOURLY_CAP_DEFAULT = "15"
_MIN_QUEUED_DEFAULT = "5"

# CLI-only coder prefixes that cannot go through the HTTP API path
_CLI_ONLY_CODERS = frozenset({"aider", "cursor", "copilot", "cline"})

# Task kinds that must run through the full runner pipeline
_CLI_ONLY_KINDS = frozenset({"replay"})

# Slug prefixes that require CLI execution
_CLI_ONLY_SLUG_PREFIXES = ("ROTATE_KEY:",)


def _normalized_swarm_model(provider: str, model: str, task: dict, registry: dict) -> tuple:
    """Resolve generic vendor routes to a real model accepted by that provider.

    Admission intentionally stores portable route labels (for example ``openai``
    or ``google``).  The HTTP fast lane must translate those labels at its launch
    boundary instead of sending them as literal model IDs.  Choose the provider's
    fast/mid/heavy tier from task risk so the translation also preserves the
    triage decision rather than blindly selecting the cheapest model.
    """
    provider = {"google": "gemini", "anthropic": "claude"}.get(provider, provider)
    spec = (registry or {}).get(provider) or {}
    models = spec.get("models") or {}
    current = str(model or "").strip()
    if not models:
        return provider, current
    if current in models.values():
        return provider, current

    aliases = {provider, "google" if provider == "gemini" else "",
               "anthropic" if provider == "claude" else "", "openai"}
    valid_prefix = {
        "openai": ("gpt-", "o1", "o3", "o4", "o5"),
        "gemini": ("gemini-",),
        "claude": ("claude-",),
        "deepseek": ("deepseek-",),
        "groq": ("llama-", "mixtral-"),
        "xai": ("grok-",),
    }.get(provider, ())
    if current and current not in aliases and current.startswith(valid_prefix):
        return provider, current

    kind = str((task or {}).get("kind") or "build").lower()
    if (task or {}).get("material") or kind in {"security", "legal", "architecture"}:
        tier = "heavy"
    elif kind in {"mechanical", "chore", "docs", "cleanup", "test"}:
        tier = "fast"
    else:
        tier = "mid"
    return provider, models.get(tier) or models.get("mid") or next(iter(models.values()))

# ---------------------------------------------------------------------------
# Thread-safe spend tracking (reads swarm_executor's spend log)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_local_spend: list = []  # (timestamp, usd) — tracks spend from THIS module


def _hourly_spend() -> float:
    """Total USD spent in the last hour across swarm_executor + this module."""
    now = time.time()
    # Read swarm_executor's spend log
    try:
        import swarm_executor
        with swarm_executor._budget_lock:
            se_hour = sum(u for t, u in swarm_executor._spend_log if now - t < 3600)
    except Exception:
        se_hour = 0.0
    # Add our own tracking
    with _lock:
        local_hour = sum(u for t, u in _local_spend if now - t < 3600)
    return se_hour + local_hour


def _record_spend(usd: float):
    """Record spend from a swarm dispatch."""
    with _lock:
        _local_spend.append((time.time(), usd))
        # Prune entries older than 2 hours
        cutoff = time.time() - 7200
        while _local_spend and _local_spend[0][0] < cutoff:
            _local_spend.pop(0)


def _budget_ok() -> bool:
    """Check if we're under the hourly cap."""
    cap = float(os.environ.get("ORCH_SWARM_HOURLY_CAP", _HOURLY_CAP_DEFAULT))
    spent = _hourly_spend()
    if spent >= cap:
        log.info("parallel_dispatch: hourly cap $%.2f reached ($%.2f spent)", cap, spent)
        return False
    return True


# ---------------------------------------------------------------------------
# API eligibility check
# ---------------------------------------------------------------------------

def _is_api_eligible(task: dict) -> bool:
    """Determine if a task can be dispatched via direct HTTP API (swarm_executor)
    rather than requiring a CLI subprocess."""
    try:
        # Check force_coder — if set to a CLI-only coder, must use CLI
        fc = str(task.get("force_coder") or "").lower()
        if fc:
            # "swarm:*" force_coders are API-eligible
            if fc.startswith("swarm:"):
                return True
            # Known CLI-only coders
            for cli_coder in _CLI_ONLY_CODERS:
                if cli_coder in fc:
                    return False

        # Check kind
        kind = str(task.get("kind") or "").lower()
        if kind in _CLI_ONLY_KINDS:
            return False

        # Check slug prefixes
        slug = str(task.get("slug") or "")
        for prefix in _CLI_ONLY_SLUG_PREFIXES:
            if slug.startswith(prefix):
                return False

        # No prompt = nothing to send to API
        if not (task.get("prompt") or "").strip():
            return False

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Batch claiming
# ---------------------------------------------------------------------------

def _claim_batch(runner_id: str, max_batch: int) -> list:
    """Claim up to max_batch tasks from the queue. Fail-soft: returns
    whatever was successfully claimed, never raises."""
    claimed = []
    for _ in range(max_batch):
        try:
            t = db.claim_task(runner_id)
            if t is None:
                break  # queue exhausted or nothing claimable
            claimed.append(t)
        except Exception as e:
            log.warning("parallel_dispatch: claim_task error: %s", e)
            break  # don't keep hammering on errors
    return claimed


# ---------------------------------------------------------------------------
# Swarm dispatch for a single task
# ---------------------------------------------------------------------------

def _dispatch_one_api(task: dict) -> dict:
    """Run a single task through swarm_executor.run_swarm(). Returns the result dict
    with the task_id attached. Fail-soft: never raises."""
    task_id = task.get("id", "?")
    slug = task.get("slug", "?")
    try:
        import swarm_executor

        prompt = task.get("prompt", "")
        model = task.get("model") or task.get("_force_model") or "claude-haiku-4-5-20251001"

        # Determine provider from force_coder if set
        provider = ""
        fc = str(task.get("force_coder") or "")
        if fc.startswith("swarm:"):
            provider = fc.split(":", 1)[1]
        if provider:
            provider, model = _normalized_swarm_model(
                provider, model, task, swarm_executor.PROVIDERS)

        # Determine repo path for cwd
        cwd = ""
        project_row = {}
        try:
            projects = {}
            try:
                from runner import _projects_cache
                projects = _projects_cache() if callable(_projects_cache) else {}
            except Exception:
                pass
            if not projects:
                projects = {p["id"]: p for p in (db.select("projects", {"select": "id,repo_path"}) or [])}
            proj = projects.get(task.get("project_id"), {})
            project_row = proj
            cwd = db.localize_repo_path(proj.get("repo_path", "")) if hasattr(db, "localize_repo_path") else ""
        except Exception:
            pass

        tournament_on = os.environ.get("ORCH_PATCH_TOURNAMENT", "true").lower() in ("1", "true", "yes", "on")
        release_fix = str(task.get("slug") or "").startswith(("qafix-", "buildfix-", "relfix-", "deployfix-", "toolchain-repair-"))
        if tournament_on and release_fix and cwd:
            import patch_tournament, provider_credentials
            providers = [p for p in ("xai", "deepseek", "groq", "openai", "google")
                         if p in swarm_executor.PROVIDERS and provider_credentials.has(p)]
            if len(providers) >= 2:
                result = patch_tournament.run_live(task, cwd, providers[:3],
                                                   test_cmd=project_row.get("test_cmd") or "",
                                                   apply_winner=False)
            else:
                result = swarm_executor.run_swarm(prompt=prompt, model=model, provider=provider,
                                                  cwd=cwd, timeout=300, mode="diff")
        else:
            result = swarm_executor.run_swarm(prompt=prompt, model=model, provider=provider,
                                              cwd=cwd, timeout=300, mode="diff")

        cost = result.get("cost_usd", 0.0)
        _record_spend(cost)

        # Update task based on result
        if result.get("returncode", 1) == 0 and result.get("text"):
            db.update("tasks", {"id": task_id}, {
                "state": "DONE",
                "result": (result.get("text") or "")[:60000],
                "note": f"swarm-parallel:{result.get('coder', 'api')} cost=${cost:.4f}",
                "updated_at": "now()",
            })
            log.info("parallel_dispatch: DONE %s (%.4f USD)", slug, cost)
            return {"task_id": task_id, "slug": slug, "status": "done", "cost_usd": cost}
        else:
            # Failed — requeue for normal runner pipeline
            db.update("tasks", {"id": task_id}, {
                "state": "QUEUED",
                "account": None,
                "note": f"swarm-parallel-fail: {(result.get('text') or 'empty')[:200]}",
                "updated_at": "now()",
            })
            log.info("parallel_dispatch: REQUEUE %s (swarm returned rc=%s)", slug, result.get("returncode"))
            return {"task_id": task_id, "slug": slug, "status": "requeued", "cost_usd": cost}

    except Exception as e:
        # Fail-soft: requeue the task so the normal pipeline can handle it
        try:
            db.update("tasks", {"id": task_id}, {
                "state": "QUEUED",
                "account": None,
                "note": f"swarm-parallel-error: {str(e)[:200]}",
                "updated_at": "now()",
            })
        except Exception:
            pass
        log.warning("parallel_dispatch: error on %s: %s", slug, e)
        return {"task_id": task_id, "slug": slug, "status": "error", "cost_usd": 0.0}


def _dispatch_one_cli(task: dict, run_task_safe_fn) -> dict:
    """Dispatch a CLI-only task through the normal runner pipeline.
    The thread is started inline and tracked."""
    task_id = task.get("id", "?")
    slug = task.get("slug", "?")
    try:
        th = threading.Thread(target=run_task_safe_fn, args=(task,), daemon=True)
        th.start()
        return {"task_id": task_id, "slug": slug, "status": "cli_dispatched", "thread": th, "cost_usd": 0.0}
    except Exception as e:
        log.warning("parallel_dispatch: CLI dispatch error on %s: %s", slug, e)
        return {"task_id": task_id, "slug": slug, "status": "error", "cost_usd": 0.0}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def should_use_swarm(eff_limit: int, active_count: int) -> bool:
    """Decide whether to use batch swarm dispatch this loop iteration.

    Returns True when:
      - ORCH_SWARM_DISPATCH env var is "true"
      - There's headroom (active_count < eff_limit - 2)
      - Budget is under the hourly cap
    """
    try:
        enabled = os.environ.get("ORCH_SWARM_DISPATCH", _DISPATCH_DEFAULT).lower() in ("true", "1", "yes")
        if not enabled:
            return False
        if active_count >= eff_limit - 2:
            return False
        if not _budget_ok():
            return False
        return True
    except Exception:
        return False


def dispatch_swarm_batch(runner_id: str, active_threads: list = None,
                         run_task_safe_fn=None, max_batch: int = 0) -> dict:
    """Claim a batch of tasks and dispatch them in parallel.

    API-eligible tasks go through swarm_executor concurrently.
    CLI-only tasks are dispatched through the normal _run_task_safe threading.

    Args:
        runner_id: This runner's identity string.
        active_threads: The runner's `active` list — CLI threads are appended here.
        run_task_safe_fn: The runner's _run_task_safe function for CLI fallback.
        max_batch: Override batch size (0 = use env var).

    Returns:
        Stats dict: {dispatched, api_tasks, cli_tasks, errors, cost_usd}
    """
    stats = {"dispatched": 0, "api_tasks": 0, "cli_tasks": 0, "errors": 0, "cost_usd": 0.0}
    if active_threads is None:
        active_threads = []

    try:
        if not max_batch:
            max_batch = int(os.environ.get("ORCH_SWARM_BATCH_SIZE", _BATCH_DEFAULT))

        # Budget gate
        if not _budget_ok():
            return stats

        # Claim batch
        claimed = _claim_batch(runner_id, max_batch)
        if not claimed:
            return stats

        stats["dispatched"] = len(claimed)

        # Partition into API-eligible vs CLI-only
        api_tasks = []
        cli_tasks = []
        for t in claimed:
            if _is_api_eligible(t):
                api_tasks.append(t)
            else:
                cli_tasks.append(t)

        stats["api_tasks"] = len(api_tasks)
        stats["cli_tasks"] = len(cli_tasks)

        log.info("parallel_dispatch: batch=%d (api=%d cli=%d)",
                 len(claimed), len(api_tasks), len(cli_tasks))

        # Dispatch CLI tasks first (they start their own threads)
        if run_task_safe_fn and cli_tasks:
            for t in cli_tasks:
                result = _dispatch_one_cli(t, run_task_safe_fn)
                if result.get("thread"):
                    active_threads.append(result["thread"])
                if result["status"] == "error":
                    stats["errors"] += 1

        # Dispatch API tasks concurrently via ThreadPoolExecutor
        if api_tasks:
            max_workers = min(len(api_tasks), 20)  # cap concurrent threads
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_dispatch_one_api, t): t for t in api_tasks}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        stats["cost_usd"] += result.get("cost_usd", 0.0)
                        if result["status"] == "error":
                            stats["errors"] += 1
                    except Exception as e:
                        stats["errors"] += 1
                        log.warning("parallel_dispatch: future error: %s", e)

        log.info("parallel_dispatch: done — %d dispatched, %d errors, $%.4f spent",
                 stats["dispatched"], stats["errors"], stats["cost_usd"])

    except Exception as e:
        log.warning("parallel_dispatch: batch dispatch error: %s", e)

    return stats


def hourly_spend() -> float:
    """Public accessor for current hourly spend. Used by monitoring."""
    try:
        return _hourly_spend()
    except Exception:
        return 0.0


def stats() -> dict:
    """Operator-visible stats snapshot."""
    try:
        cap = float(os.environ.get("ORCH_SWARM_HOURLY_CAP", _HOURLY_CAP_DEFAULT))
        spent = _hourly_spend()
        return {
            "enabled": os.environ.get("ORCH_SWARM_DISPATCH", _DISPATCH_DEFAULT).lower() in ("true", "1", "yes"),
            "batch_size": int(os.environ.get("ORCH_SWARM_BATCH_SIZE", _BATCH_DEFAULT)),
            "hourly_cap_usd": cap,
            "hourly_spend_usd": round(spent, 4),
            "headroom_usd": round(max(0, cap - spent), 4),
        }
    except Exception:
        return {}
