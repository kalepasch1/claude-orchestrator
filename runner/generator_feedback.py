#!/usr/bin/env python3
"""
generator_feedback.py — Outcome feedback into task generators (50X).

Prevents generators from re-creating tasks that have already failed, been
decomposed by bankruptcy_decompose, or been eliminated by queue_elimination.

Before a generator queues a new task, it should check:
  1. Has a similar task failed in the last 72h?
  2. Has a similar task been decomposed (bankrupt)?
  3. Is there already a similar task in the queue?

This prevents the 500+ task backlog from accumulating with doomed patterns.

Usage:
    import generator_feedback
    if generator_feedback.should_generate(prompt, project_name, kind):
        # ok to queue this task
    else:
        # skip — similar task recently failed
"""
import os, sys, json, time, hashlib, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

FEEDBACK_ENABLED = os.environ.get("ORCH_GENERATOR_FEEDBACK", "true").lower() in ("true", "1", "yes")
FAILURE_WINDOW_H = int(os.environ.get("ORCH_GEN_FAILURE_WINDOW_H", "72"))
SIMILARITY_THRESHOLD = float(os.environ.get("ORCH_GEN_SIMILARITY", "0.7"))


def _tokenize(text):
    """Simple word tokenization for Jaccard similarity."""
    return set(re.findall(r'\w{3,}', text.lower()))


def _jaccard(a, b):
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0
    return len(a & b) / len(a | b)


def _recent_failures(project_name="", limit=50):
    """Get recent failed/blocked/decomposed tasks."""
    try:
        params = {
            "select": "prompt,state,kind,slug,note",
            "state": "in.(BLOCKED,DECOMPOSED,FAILED)",
            "order": "updated_at.desc",
            "limit": str(limit),
        }
        if project_name:
            # Get project_id first
            projects = db.select("projects", {"select": "id", "name": f"eq.{project_name}"})
            if projects:
                params["project_id"] = f"eq.{projects[0]['id']}"
        return db.select("tasks", params) or []
    except Exception:
        return []


def _queued_tasks(project_name="", limit=100):
    """Get currently queued tasks."""
    try:
        params = {
            "select": "prompt,kind,slug",
            "state": "eq.QUEUED",
            "order": "created_at.desc",
            "limit": str(limit),
        }
        return db.select("tasks", params) or []
    except Exception:
        return []


def should_generate(prompt, project_name="", kind="feature"):
    """Check if a task with this prompt should be generated.

    Returns: {generate: bool, reason: str, similar_to: str}
    """
    if not FEEDBACK_ENABLED:
        return {"generate": True, "reason": "feedback disabled"}

    prompt_tokens = _tokenize(prompt)
    if not prompt_tokens:
        return {"generate": True, "reason": "empty prompt"}

    # Check 1: Similar recent failures
    failures = _recent_failures(project_name)
    for f in failures:
        f_tokens = _tokenize(f.get("prompt", ""))
        sim = _jaccard(prompt_tokens, f_tokens)
        if sim >= SIMILARITY_THRESHOLD:
            return {
                "generate": False,
                "reason": f"similar to recent {f.get('state', 'failed')} task (sim={sim:.0%})",
                "similar_to": f.get("slug", ""),
                "similarity": round(sim, 3),
            }

    # Check 2: Already in queue
    queued = _queued_tasks(project_name)
    for q in queued:
        q_tokens = _tokenize(q.get("prompt", ""))
        sim = _jaccard(prompt_tokens, q_tokens)
        if sim >= SIMILARITY_THRESHOLD:
            return {
                "generate": False,
                "reason": f"similar task already queued (sim={sim:.0%})",
                "similar_to": q.get("slug", ""),
                "similarity": round(sim, 3),
            }

    return {"generate": True, "reason": "no similar failures or duplicates"}


def filter_batch(tasks, project_name=""):
    """Filter a batch of generated tasks, removing those with similar failures.

    Args:
        tasks: list of {prompt, kind, ...} dicts
    Returns: list of tasks that passed the filter
    """
    passed = []
    for t in tasks:
        check = should_generate(t.get("prompt", ""), project_name, t.get("kind", "feature"))
        if check["generate"]:
            passed.append(t)
        else:
            print(f"[gen-feedback] filtered: {check['reason']} (similar_to={check.get('similar_to', '')})")
    return passed


def run():
    """Periodic: report generator feedback stats."""
    failures = _recent_failures(limit=100)
    queued = _queued_tasks(limit=200)

    blocked = sum(1 for f in failures if f.get("state") == "BLOCKED")
    decomposed = sum(1 for f in failures if f.get("state") == "DECOMPOSED")

    print(f"[gen-feedback] {len(failures)} recent failures "
          f"({blocked} blocked, {decomposed} decomposed), "
          f"{len(queued)} queued — generators will avoid similar patterns")


if __name__ == "__main__":
    run()
