#!/usr/bin/env python3
"""
queue_optimizer.py — Continuous task queue topology optimization.

Removes false dependencies, detects redundant tasks, flags oversized tasks
for splitting, and reorders for maximum parallelism.  Called periodically by
the queue_preopt daemon (typically every ORCH_OPTIMIZER_INTERVAL seconds).

All modifications are:
  - Rate-limited to MAX_MODS_PER_PASS per optimize() call
  - Logged to resource_events with full audit context
  - Skipped entirely when ORCH_OPTIMIZER_DRY_RUN is "true"
  - Never applied to RUNNING or RETRY tasks

Usage:
    import queue_optimizer
    summary = queue_optimizer.optimize()   # run all passes
    queue_optimizer.stats()                # cumulative counters
"""
import os, sys, re, hashlib, json, datetime, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import log as _log_mod

_log = _log_mod.get("queue_optimizer")

# ---------------------------------------------------------------------------
# Configuration — env vars with sensible defaults
# ---------------------------------------------------------------------------
def _enabled():
    return os.environ.get("ORCH_QUEUE_OPTIMIZER_ENABLED", "true").lower() in ("true", "1", "yes")

def _interval():
    return int(os.environ.get("ORCH_OPTIMIZER_INTERVAL", "120") or 120)

def _dry_run():
    return os.environ.get("ORCH_OPTIMIZER_DRY_RUN", "false").lower() in ("true", "1", "yes")

def _split_threshold():
    return int(os.environ.get("ORCH_SPLIT_THRESHOLD", "8000") or 8000)

MAX_MODS_PER_PASS = 10

# ---------------------------------------------------------------------------
# Cumulative statistics (module-level singleton, thread-safe)
# ---------------------------------------------------------------------------
_stats_lock = threading.Lock()
_cumulative = {
    "passes": 0,
    "false_deps_removed": 0,
    "redundant_tasks_removed": 0,
    "oversized_flagged": 0,
    "bottlenecks_found": 0,
    "priority_boosts": 0,
}


def stats():
    """Return cumulative optimization statistics."""
    with _stats_lock:
        return dict(_cumulative)


def _bump(key, n=1):
    with _stats_lock:
        _cumulative[key] = _cumulative.get(key, 0) + n


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------
_IMMUTABLE_STATES = {"RUNNING", "RETRY"}
_FILE_PATH_RE = re.compile(r'(?:^|[\s,;])([a-zA-Z0-9_./-]+\.[a-zA-Z]{1,6})(?:[\s,;]|$)')
_UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
_TS_RE = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}')


def _event(kind, detail="", action=""):
    """Record an audit event in resource_events.  Never raises."""
    try:
        db.insert("resource_events", {
            "kind": kind,
            "detail": str(detail)[:500],
            "action": str(action)[:500],
        })
    except Exception:
        pass


def _now_iso():
    return datetime.datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# Task fetching
# ---------------------------------------------------------------------------
def _queued_tasks(columns="id,slug,prompt,deps,project_id,state,note,created_at"):
    """Fetch all QUEUED tasks.  Returns [] on any error."""
    try:
        return db.select("tasks", {
            "select": columns,
            "state": "eq.QUEUED",
            "order": "created_at.asc",
        }) or []
    except Exception as e:
        _log.debug("failed to fetch queued tasks: %s", e)
        return []


def _task_by_slug(slug):
    """Fetch a single task by slug.  Returns None on miss/error."""
    try:
        rows = db.select("tasks", {"select": "id,slug,prompt,deps,state,project_id,note", "slug": f"eq.{slug}"})
        return rows[0] if rows else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1. Remove false dependencies
# ---------------------------------------------------------------------------
def _extract_file_paths(text):
    """Extract plausible file paths from a prompt string."""
    if not text:
        return set()
    return {m.group(1) for m in _FILE_PATH_RE.finditer(str(text))}


def _remove_false_deps():
    """Find and remove unnecessary dependencies.

    A dep is "false" (advisory only) when:
      - Both the task and its dep have explicit file scopes (>= 1 file path each)
      - The file scopes have zero overlap

    Returns the count of deps removed.
    """
    removed = 0
    mod_budget = MAX_MODS_PER_PASS
    dry = _dry_run()

    tasks = _queued_tasks()
    for task in tasks:
        if mod_budget <= 0:
            break
        deps = task.get("deps") or []
        if not deps:
            continue

        task_files = _extract_file_paths(task.get("prompt", ""))
        if not task_files:
            continue  # no explicit file scope — cannot safely judge

        false_deps = []
        for dep_slug in deps:
            dep_task = _task_by_slug(dep_slug)
            if not dep_task:
                continue
            if dep_task.get("state") in _IMMUTABLE_STATES:
                continue

            dep_files = _extract_file_paths(dep_task.get("prompt", ""))
            if not dep_files:
                continue  # dep has no explicit file scope — keep the dep (safety)

            overlap = task_files & dep_files
            if len(overlap) == 0:
                false_deps.append(dep_slug)

        if not false_deps:
            continue

        new_deps = [d for d in deps if d not in false_deps]
        slug = task.get("slug", task.get("id", "?")[:8])

        if dry:
            _log.debug("[dry-run] would remove %d false deps from %s: %s",
                       len(false_deps), slug, false_deps)
        else:
            try:
                note = (task.get("note") or "") + f"\n[queue-opt {_now_iso()}] removed false deps: {false_deps}"
                db.update("tasks", {"id": task["id"]}, {"deps": new_deps, "note": note.strip()})
                _event("queue_opt_dep_removal",
                       detail=f"task={slug} removed={false_deps}",
                       action="remove_false_deps")
                _log.debug("removed %d false deps from %s", len(false_deps), slug)
            except Exception as e:
                _log.debug("failed to update deps for %s: %s", slug, e)
                continue

        removed += len(false_deps)
        mod_budget -= 1

    _bump("false_deps_removed", removed)
    return removed


# ---------------------------------------------------------------------------
# 2. Detect redundant tasks
# ---------------------------------------------------------------------------
def _normalize_prompt(prompt):
    """Normalize a prompt for deduplication: lowercase, strip whitespace, remove UUIDs/timestamps."""
    if not prompt:
        return ""
    text = str(prompt).lower()
    text = _UUID_RE.sub("", text)
    text = _TS_RE.sub("", text)
    text = " ".join(text.split())  # collapse whitespace
    return text.strip()


def _prompt_hash(prompt):
    return hashlib.sha256(_normalize_prompt(prompt).encode("utf-8", errors="replace")).hexdigest()[:16]


def _detect_redundant_tasks():
    """Find duplicate QUEUED tasks within the same project.

    If two QUEUED tasks in the same project have identical normalized prompt
    hashes, marks the NEWER one as DONE with a redundancy note.  Never removes
    the older task.

    Returns count of redundant tasks removed.
    """
    removed = 0
    mod_budget = MAX_MODS_PER_PASS
    dry = _dry_run()

    tasks = _queued_tasks()  # ordered by created_at asc (oldest first)

    # Group by (project_id, prompt_hash)
    seen = {}  # (project_id, hash) -> first task slug
    for task in tasks:
        if mod_budget <= 0:
            break
        pid = task.get("project_id", "")
        ph = _prompt_hash(task.get("prompt", ""))
        if not ph:
            continue

        key = (pid, ph)
        slug = task.get("slug", task.get("id", "?")[:8])

        if key in seen:
            older_slug = seen[key]
            if dry:
                _log.debug("[dry-run] would mark %s redundant (duplicate of %s)", slug, older_slug)
            else:
                try:
                    note = f"redundant: duplicate of {older_slug}"
                    db.update("tasks", {"id": task["id"]}, {
                        "state": "DONE",
                        "note": note,
                        "finished_at": _now_iso(),
                    })
                    _event("queue_opt_redundant",
                           detail=f"task={slug} duplicate_of={older_slug} hash={ph}",
                           action="mark_redundant")
                    _log.debug("marked %s redundant (duplicate of %s)", slug, older_slug)
                except Exception as e:
                    _log.debug("failed to mark %s redundant: %s", slug, e)
                    continue

            removed += 1
            mod_budget -= 1
        else:
            seen[key] = slug

    _bump("redundant_tasks_removed", removed)
    return removed


# ---------------------------------------------------------------------------
# 3. Split oversized tasks (flag only)
# ---------------------------------------------------------------------------
def _count_file_paths(prompt):
    """Count distinct file paths in a prompt."""
    return len(_extract_file_paths(prompt))


def _split_oversized_tasks():
    """Flag tasks that are too complex for a single pass.

    A task is "oversized" if its prompt exceeds ORCH_SPLIT_THRESHOLD chars
    AND mentions 4+ distinct file paths.  Flagged via task note — does NOT
    auto-split (the planner decides).

    Returns count of tasks flagged.
    """
    flagged = 0
    mod_budget = MAX_MODS_PER_PASS
    dry = _dry_run()
    threshold = _split_threshold()

    tasks = _queued_tasks()
    for task in tasks:
        if mod_budget <= 0:
            break

        prompt = task.get("prompt") or ""
        note = task.get("note") or ""

        # Skip if already flagged
        if "[queue-opt] oversized" in note:
            continue

        if len(prompt) <= threshold:
            continue

        file_count = _count_file_paths(prompt)
        if file_count < 4:
            continue

        slug = task.get("slug", task.get("id", "?")[:8])

        if dry:
            _log.debug("[dry-run] would flag %s as oversized (%d chars, %d files)",
                       slug, len(prompt), file_count)
        else:
            try:
                new_note = note + (
                    f"\n[queue-opt {_now_iso()}] oversized: {len(prompt)} chars, "
                    f"{file_count} files — consider splitting"
                )
                db.update("tasks", {"id": task["id"]}, {"note": new_note.strip()})
                _event("queue_opt_oversized",
                       detail=f"task={slug} chars={len(prompt)} files={file_count}",
                       action="flag_oversized")
                _log.debug("flagged %s as oversized (%d chars, %d files)", slug, len(prompt), file_count)
            except Exception as e:
                _log.debug("failed to flag %s as oversized: %s", slug, e)
                continue

        flagged += 1
        mod_budget -= 1

    _bump("oversized_flagged", flagged)
    return flagged


# ---------------------------------------------------------------------------
# 4. Optimize parallelism
# ---------------------------------------------------------------------------
def _optimize_parallelism():
    """Analyze the dep graph for better lane utilization.

    Identifies bottleneck tasks (many tasks blocked on one) and suggests
    priority boosts for them.

    Returns {"bottlenecks_found": int, "priority_boosts": int}.
    """
    bottlenecks_found = 0
    priority_boosts = 0
    mod_budget = MAX_MODS_PER_PASS
    dry = _dry_run()

    tasks = _queued_tasks()
    if not tasks:
        return {"bottlenecks_found": 0, "priority_boosts": 0}

    # Build reverse dep map: slug -> count of tasks that depend on it
    dep_counts = {}
    for task in tasks:
        for dep in (task.get("deps") or []):
            dep_counts[dep] = dep_counts.get(dep, 0) + 1

    # A slug is a bottleneck if 3+ other tasks depend on it
    bottleneck_threshold = 3
    for slug, count in sorted(dep_counts.items(), key=lambda x: -x[1]):
        if mod_budget <= 0:
            break
        if count < bottleneck_threshold:
            continue

        bottlenecks_found += 1

        # Look up the bottleneck task — only boost if it's QUEUED
        bt = _task_by_slug(slug)
        if not bt or bt.get("state") != "QUEUED":
            continue

        note = bt.get("note") or ""
        if "[queue-opt] priority-boost" in note:
            continue  # already boosted

        if dry:
            _log.debug("[dry-run] would priority-boost %s (blocks %d tasks)", slug, count)
        else:
            try:
                new_note = note + (
                    f"\n[queue-opt {_now_iso()}] priority-boost: blocks {count} downstream tasks"
                )
                db.update("tasks", {"id": bt["id"]}, {"note": new_note.strip()})
                _event("queue_opt_priority_boost",
                       detail=f"task={slug} blocks={count}",
                       action="priority_boost")
                _log.debug("priority-boosted %s (blocks %d tasks)", slug, count)
            except Exception as e:
                _log.debug("failed to boost %s: %s", slug, e)
                continue

        priority_boosts += 1
        mod_budget -= 1

    _bump("bottlenecks_found", bottlenecks_found)
    _bump("priority_boosts", priority_boosts)
    return {"bottlenecks_found": bottlenecks_found, "priority_boosts": priority_boosts}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def optimize():
    """Run all optimization passes.  Returns summary stats dict."""
    if not _enabled():
        _log.debug("queue optimizer disabled")
        return {"enabled": False}

    _bump("passes")
    _log.debug("starting optimization pass")

    summary = {}
    try:
        summary["false_deps_removed"] = _remove_false_deps()
    except Exception as e:
        _log.debug("_remove_false_deps error: %s", e)
        summary["false_deps_removed"] = 0

    try:
        summary["redundant_tasks_removed"] = _detect_redundant_tasks()
    except Exception as e:
        _log.debug("_detect_redundant_tasks error: %s", e)
        summary["redundant_tasks_removed"] = 0

    try:
        summary["oversized_flagged"] = _split_oversized_tasks()
    except Exception as e:
        _log.debug("_split_oversized_tasks error: %s", e)
        summary["oversized_flagged"] = 0

    try:
        par = _optimize_parallelism()
        summary.update(par)
    except Exception as e:
        _log.debug("_optimize_parallelism error: %s", e)
        summary["bottlenecks_found"] = 0
        summary["priority_boosts"] = 0

    summary["dry_run"] = _dry_run()
    _log.debug("optimization pass complete: %s", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(optimize(), indent=2))
