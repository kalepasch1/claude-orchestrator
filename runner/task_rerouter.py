#!/usr/bin/env python3
"""
task_rerouter.py – AI-driven task re-routing with patch template adaptation.

Analyzes failed/quarantined tasks, matches them against known patch templates
and prior merged diffs, and re-routes them with adapted prompts that increase
the likelihood of success on retry.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, re, json, datetime, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAX_REROUTE_ATTEMPTS = int(os.environ.get("ORCH_MAX_REROUTE", "3"))
SIMILARITY_THRESHOLD = float(os.environ.get("ORCH_SIMILARITY_MIN", "0.3"))

_lock = threading.Lock()
_STATE = {
    "rerouted": 0,
    "templates_matched": 0,
    "last_run": None,
}

# Common failure -> fix strategy mappings
STRATEGY_MAP = {
    "test-failure": {
        "action": "add_test_context",
        "prompt_prefix": "Prior tests failed. Fix the specific test assertions before re-attempting. ",
    },
    "build-failure": {
        "action": "add_build_context",
        "prompt_prefix": "Prior build failed. Check imports, type errors, and missing dependencies. ",
    },
    "merge-conflict": {
        "action": "rebase_first",
        "prompt_prefix": "Prior attempt had merge conflicts. Rebase onto latest base first. ",
    },
    "timeout": {
        "action": "simplify_scope",
        "prompt_prefix": "Prior attempt timed out. Reduce scope to the minimal viable change. ",
    },
    "missing-branch": {
        "action": "reconstruct",
        "prompt_prefix": "Branch is missing. Reconstruct the minimal patch from the original intent. ",
    },
}


def _classify_failure(note):
    """Classify a task failure note into a strategy category."""
    if not note:
        return "unknown"
    note_lower = note.lower()
    if "test" in note_lower and ("fail" in note_lower or "error" in note_lower):
        return "test-failure"
    if "build" in note_lower and ("fail" in note_lower or "error" in note_lower):
        return "build-failure"
    if "merge" in note_lower and "conflict" in note_lower:
        return "merge-conflict"
    if "timeout" in note_lower or "timed out" in note_lower:
        return "timeout"
    if "missing" in note_lower and "branch" in note_lower:
        return "missing-branch"
    return "unknown"


def _find_template_match(slug, project_id):
    """
    Search for matching patch templates from prior merged diffs.

    Returns best match or None.
    """
    try:
        import db
        # Look for merged tasks in the same project with similar slugs
        parts = slug.replace("-", " ").split()
        keywords = [p for p in parts if len(p) > 3][:5]

        merged = db.select("tasks", {
            "select": "slug,note,kind",
            "project_id": f"eq.{project_id}",
            "state": "eq.MERGED",
            "limit": "20",
            "order": "updated_at.desc",
        }) or []

        best_match = None
        best_score = 0

        for m in merged:
            m_slug = m.get("slug", "")
            score = sum(1 for kw in keywords if kw in m_slug) / max(len(keywords), 1)
            if score > best_score and score >= SIMILARITY_THRESHOLD:
                best_score = score
                best_match = {
                    "slug": m_slug,
                    "similarity": round(score, 3),
                    "note": (m.get("note") or "")[:200],
                }

        return best_match
    except Exception:
        return None


def analyze_for_reroute(task):
    """
    Analyze a task and recommend a re-routing strategy.

    Args:
        task: dict with slug, note, prompt, project_id, attempt

    Returns dict with strategy, adapted_prompt_prefix, template_match.
    """
    note = task.get("note") or ""
    slug = task.get("slug") or ""
    project_id = task.get("project_id") or ""
    attempt = task.get("attempt", 0)

    if attempt >= MAX_REROUTE_ATTEMPTS:
        return {
            "action": "quarantine",
            "reason": f"Max reroute attempts ({MAX_REROUTE_ATTEMPTS}) exceeded",
            "slug": slug,
        }

    failure_type = _classify_failure(note)
    strategy = STRATEGY_MAP.get(failure_type, {
        "action": "generic_retry",
        "prompt_prefix": "Prior attempt failed. Review the failure context and retry. ",
    })

    template = _find_template_match(slug, project_id)

    result = {
        "slug": slug,
        "failure_type": failure_type,
        "strategy": strategy["action"],
        "prompt_prefix": strategy["prompt_prefix"],
        "template_match": template,
        "attempt": attempt + 1,
        "analyzed_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    with _lock:
        _STATE["rerouted"] += 1
        if template:
            _STATE["templates_matched"] += 1

    return result


def reroute_quarantined(dry_run=True):
    """
    Scan quarantined tasks and generate reroute recommendations.

    In non-dry-run mode, requeues tasks with adapted prompts.
    """
    try:
        import db
        tasks = db.select("tasks", {
            "select": "id,slug,note,prompt,project_id,attempt",
            "state": "eq.QUARANTINED",
            "limit": "20",
            "order": "updated_at.asc",
        }) or []
    except Exception:
        return {"error": "db unavailable"}

    recommendations = []
    for t in tasks:
        rec = analyze_for_reroute(t)
        recommendations.append(rec)

        if not dry_run and rec["strategy"] != "quarantine":
            try:
                import db
                db.update("tasks", {"id": f"eq.{t['id']}"}, {
                    "state": "QUEUED",
                    "attempt": rec["attempt"],
                    "note": f"Rerouted: {rec['strategy']} (was: {rec['failure_type']})",
                })
            except Exception:
                pass

    with _lock:
        _STATE["last_run"] = datetime.datetime.utcnow().isoformat() + "Z"

    return {
        "analyzed": len(recommendations),
        "reroutable": sum(1 for r in recommendations if r["strategy"] != "quarantine"),
        "quarantine": sum(1 for r in recommendations if r["strategy"] == "quarantine"),
        "recommendations": recommendations,
        "dry_run": dry_run,
    }


def stats():
    with _lock:
        return dict(_STATE)


def run():
    """Entry point for periodic jobs — analyze quarantined tasks."""
    return reroute_quarantined(dry_run=True)


if __name__ == "__main__":
    print(json.dumps(reroute_quarantined(dry_run=True), indent=2, default=str))
