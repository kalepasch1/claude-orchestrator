"""
queue_materializer.py — treat DECOMPOSED as parent/container state, not backlog.

Periodic job that:
1. Finds DECOMPOSED parent tasks
2. Checks if their child subtasks are all done/merged
3. Auto-closes completed parents
4. Releases only ready (dep-satisfied) children
5. Parks parents whose children are all blocked/quarantined

This prevents thousands of parked parent tasks from distorting priority and queue health.
"""
import os, sys, json, datetime, signal, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_DEPTH = int(os.environ.get("ORCH_DECOMPOSE_MAX_DEPTH", "2"))
# 2026-07-11: CHILD_SCAN_LIMIT used to be a single unordered, unpaginated fetch cap. Once the
# fleet-wide tasks table grew past that cap (observed: ~8700+ total rows against a 6000-row
# limit, with no ORDER BY -- so which 6000 rows came back was whatever Postgres happened to
# return), real children silently fell outside the snapshot. That made genuinely in-progress
# DECOMPOSED parents look "orphaned" and get incorrectly quarantined -- the dominant driver of
# a 2,400+ task QUARANTINED spike. Now paginated across the WHOLE table (bounded by
# CHILD_SCAN_MAX_PAGES as a defensive ceiling, not a silent truncation) with stable ordering so
# every page is disjoint and nothing is missed.
CHILD_SCAN_PAGE_SIZE = int(os.environ.get("ORCH_MATERIALIZER_CHILD_SCAN_PAGE_SIZE", "1000"))
CHILD_SCAN_MAX_PAGES = int(os.environ.get("ORCH_MATERIALIZER_CHILD_SCAN_MAX_PAGES", "50"))
MAX_UPDATES = int(os.environ.get("ORCH_MATERIALIZER_MAX_UPDATES", "20"))
RUN_BUDGET_S = int(os.environ.get("ORCH_MATERIALIZER_RUN_BUDGET_S", "90"))
UPDATE_TIMEOUT_S = int(os.environ.get("ORCH_MATERIALIZER_UPDATE_TIMEOUT_S", "15"))


class MaterializerTimeout(RuntimeError):
    pass


def _with_timeout(seconds, fn):
    if not hasattr(signal, "SIGALRM"):
        return fn()
    previous = signal.getsignal(signal.SIGALRM)

    def _handler(signum, frame):
        raise MaterializerTimeout(f"materializer update exceeded {seconds}s")

    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(max(1, int(seconds)))
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _update_task(task_id, patch):
    try:
        _with_timeout(UPDATE_TIMEOUT_S, lambda: db.update("tasks", {"id": task_id}, patch))
        return True
    except Exception as e:
        print(f"[materializer] update skipped for {task_id}: {str(e)[:180]}")
        return False


def _parse_deps(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _children_by_parent(parent_slugs):
    """Build parent->children using paginated reads instead of deps containment queries.

    Some task tables store deps in a shape that PostgREST rejects for `cs.[...]`, which made this
    periodic job crash. A local map is also much faster for hundreds of DECOMPOSED parents.

    Returns (child_map, complete). `complete` is False if the scan was cut short (hit the page
    ceiling or an error) -- callers MUST treat an incomplete scan as "unknown", not "no children
    found", since the orphan-detection logic downstream cannot tell the difference between a
    parent with genuinely zero children and one whose children just fell outside a partial scan.
    """
    wanted = {str(s) for s in parent_slugs if s}
    out = {s: [] for s in wanted}
    if not wanted:
        return out, True
    offset = 0
    for _ in range(CHILD_SCAN_MAX_PAGES):
        try:
            rows = db.select("tasks", {
                "select": "id,slug,state,deps",
                "order": "id.asc",
                "limit": str(CHILD_SCAN_PAGE_SIZE),
                "offset": str(offset),
            }) or []
        except Exception as e:
            print(f"[materializer] child scan failed at offset {offset}: {e}")
            return out, False
        for row in rows:
            for dep in _parse_deps(row.get("deps")):
                dep = str(dep)
                if dep in out:
                    out[dep].append(row)
        if len(rows) < CHILD_SCAN_PAGE_SIZE:
            return out, True
        offset += CHILD_SCAN_PAGE_SIZE
    print(f"[materializer] child scan hit the {CHILD_SCAN_MAX_PAGES}-page ceiling "
          f"({CHILD_SCAN_MAX_PAGES * CHILD_SCAN_PAGE_SIZE} rows) -- treating as incomplete")
    return out, False


def run():
    """Main periodic entry point."""
    closed = 0
    released = 0
    parked = 0
    attempted_updates = 0
    started = time.time()

    def can_update():
        return attempted_updates < MAX_UPDATES and (time.time() - started) < RUN_BUDGET_S

    # Find all DECOMPOSED tasks
    parents = db.select("tasks", {
        "select": "id,slug,project_id,state,deps,created_at,note",
        "state": "eq.DECOMPOSED",
        "order": "created_at.asc",
        "limit": "500"
    }) or []
    child_map, scan_complete = _children_by_parent([p.get("slug") for p in parents])
    if not scan_complete:
        # 2026-07-11: an incomplete child scan cannot be trusted to say a parent has "no
        # children" -- it may simply not have reached them yet. Orphan-quarantining on a
        # partial view was the root cause of a 2,400+ task false-positive quarantine spike.
        # Skip orphan detection entirely this run rather than act on uncertain data; the
        # close/park/release paths below only need to know about children THAT WERE FOUND,
        # so they're safe to keep running.
        print("[materializer] child scan incomplete this run -- skipping orphan detection "
              "(close/release/park of already-visible children still proceeds)")

    for parent in parents:
        pid = parent["id"]
        slug = parent.get("slug", "")

        # Find children (tasks whose deps include this parent's slug)
        children = child_map.get(slug, [])

        if not children:
            if not scan_complete:
                continue
            # No children found — this decomposed task is orphaned
            # Check if it's been sitting for > 24h with no children
            try:
                created = parent.get("created_at", "")
                if created and _age_hours(created) > 24:
                    attempted_updates += 1
                    if not can_update():
                        break
                    if _update_task(pid, {
                        "state": "QUARANTINED",
                        "note": "materializer: orphaned DECOMPOSED task (no children found after 24h)"
                    }):
                        parked += 1
            except Exception:
                pass
            continue

        child_states = [c.get("state") for c in children]

        # All children done/merged → close parent
        if all(s in ("DONE", "MERGED") for s in child_states):
            attempted_updates += 1
            if not can_update():
                break
            if _update_task(pid, {
                "state": "DONE",
                "note": f"materializer: all {len(children)} children complete"
            }):
                closed += 1
            continue

        # All children blocked/quarantined → park parent
        if all(s in ("BLOCKED", "QUARANTINED") for s in child_states):
            attempted_updates += 1
            if not can_update():
                break
            if _update_task(pid, {
                "note": f"materializer: all {len(children)} children blocked/quarantined"
            }):
                parked += 1
            continue

        # Some children still queued — check depth
        for child in children:
            if not can_update():
                break
            if child.get("state") == "DECOMPOSED":
                # Check depth — don't let decomposition go beyond MAX_DEPTH
                depth = _decomposition_depth(child.get("slug", ""), seen=set())
                if depth >= MAX_DEPTH:
                    # Flatten: convert over-deep DECOMPOSED to QUEUED
                    attempted_updates += 1
                    if _update_task(child["id"], {
                        "state": "QUEUED",
                        "note": f"materializer: flattened (depth {depth} >= max {MAX_DEPTH})"
                    }):
                        released += 1

    if closed or released or parked or attempted_updates >= MAX_UPDATES:
        print(f"[materializer] closed={closed} released={released} parked={parked} "
              f"attempted_updates={attempted_updates}/{MAX_UPDATES}")

    return {"closed": closed, "released": released, "parked": parked,
            "attempted_updates": attempted_updates}


def _decomposition_depth(slug, seen=None):
    """Count how deep a decomposition chain goes."""
    if seen is None:
        seen = set()
    if slug in seen:
        return 0
    seen.add(slug)

    try:
        children = db.select("tasks", {
            "select": "slug,state",
            "deps": f"cs.{json.dumps([slug])}",
            "state": "eq.DECOMPOSED",
            "limit": "10"
        }) or []

        if not children:
            return 1

        return 1 + max(_decomposition_depth(c["slug"], seen) for c in children)
    except Exception:
        return 1


def merge_overlapping_subtasks(parent_slug):
    """Pre-queue: merge subtasks that touch the same files into a single task."""
    try:
        children = db.select("tasks", {
            "select": "id,slug,prompt,state",
            "deps": f"cs.{json.dumps([parent_slug])}",
            "state": "eq.QUEUED",
            "limit": "50"
        }) or []

        if len(children) < 2:
            return 0

        # Group by likely file overlap (simple heuristic: similar prompt keywords)
        import re
        groups = {}
        for child in children:
            prompt = child.get("prompt", "")
            # Extract file paths from prompt
            files = set(re.findall(r'[\w/]+\.\w+', prompt))
            key = frozenset(files) if files else frozenset([child["slug"]])
            if key not in groups:
                groups[key] = []
            groups[key].append(child)

        merged = 0
        for key, group in groups.items():
            if len(group) < 2:
                continue
            # Keep the first, quarantine the rest with a pointer
            keeper = group[0]
            combined_prompt = keeper.get("prompt", "")
            for dup in group[1:]:
                combined_prompt += f"\n\n--- Also handle (merged from {dup['slug']}): ---\n"
                combined_prompt += dup.get("prompt", "")[:2000]
                db.update("tasks", {"id": dup["id"]}, {
                    "state": "QUARANTINED",
                    "note": f"materializer: merged into {keeper['slug']} (overlapping files)"
                })
                merged += 1
            if merged > 0:
                db.update("tasks", {"id": keeper["id"]}, {"prompt": combined_prompt[:30000]})

        return merged
    except Exception as e:
        print(f"[materializer] merge_overlapping error: {e}")
        return 0


def _age_hours(ts_str):
    """Parse ISO timestamp and return age in hours."""
    try:
        ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00").replace("+00:00", ""))
        return (datetime.datetime.utcnow() - ts).total_seconds() / 3600
    except Exception:
        return 0


if __name__ == "__main__":
    run()
