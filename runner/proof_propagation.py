#!/usr/bin/env python3
"""
proof_propagation.py — Active cross-project proof-pack propagation (200X).

When a proof pack succeeds in project A, actively scan projects B/C/D for
matching patterns and auto-queue zero-token replay tasks. Currently the
system passively looks up templates on task execution; this makes it proactive.

Flow:
  1. After a successful merge, check transfer_learning for cross-project matches
  2. For each matching project, check if the pattern hasn't been applied yet
  3. Queue a zero-token replay task with priority 0 (lowest, speculative)
  4. Queue elimination will pick these up and try zero-token application

Usage:
    import proof_propagation
    proof_propagation.propagate(task, project_name, merged_files, diff_text)
    # Or periodic:
    proof_propagation.run()  # scans recent merges for propagation opportunities
"""
import os, sys, json, hashlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PROPAGATION_ENABLED = os.environ.get("ORCH_PROOF_PROPAGATION", "true").lower() in ("true", "1", "yes")
MAX_PROPAGATIONS = int(os.environ.get("ORCH_MAX_PROPAGATIONS", "3"))
MIN_TRANSFER_CONF = float(os.environ.get("ORCH_PROPAGATION_MIN_CONF", "0.7"))


def _all_projects():
    try:
        return db.select("projects", {"select": "id,name,repo_path"}) or []
    except Exception:
        return []


def _already_applied(task_prompt_hash, project_id):
    """Check if this pattern has already been applied/queued for this project."""
    try:
        existing = db.select("tasks", {
            "select": "id",
            "project_id": f"eq.{project_id}",
            "slug": f"like.prop-{task_prompt_hash[:8]}*",
            "limit": 1,
        })
        return bool(existing)
    except Exception:
        return False


def propagate(task, source_project, merged_files, diff_text=""):
    """After a successful merge, propagate to other projects.

    Returns: list of {project, task_id, status} for each propagation attempt
    """
    if not PROPAGATION_ENABLED:
        return []

    results = []
    prompt = task.get("prompt", "")
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]

    projects = _all_projects()
    target_projects = [p for p in projects if p.get("name") != source_project]

    for target in target_projects[:MAX_PROPAGATIONS]:
        target_name = target.get("name", "")
        target_id = target.get("id", "")

        # Check if already applied
        if _already_applied(prompt_hash, target_id):
            continue

        # Check if transfer learning finds a match
        try:
            import transfer_learning
            transfer = transfer_learning.find_transfer(task, current_project=target_name)
            if not transfer or transfer.get("confidence", 0) < MIN_TRANSFER_CONF:
                continue
        except Exception:
            continue

        # Queue a zero-token replay task
        try:
            slug = f"prop-{prompt_hash[:8]}-{target_name}"
            adapted_prompt = (
                f"[AUTO-PROPAGATED from {source_project}] "
                f"Apply proven pattern: {prompt[:200]}..."
                f"\n\nSource files: {', '.join(merged_files[:10])}"
                f"\nTransfer confidence: {transfer['confidence']:.0%}"
            )

            db.insert("tasks", {
                "slug": slug,
                "prompt": adapted_prompt,
                "project_id": target_id,
                "kind": task.get("kind", "feature"),
                "state": "QUEUED",
                "priority": 0,  # lowest priority — speculative
                "note": f"propagated from {source_project} (conf={transfer['confidence']:.0%})",
            })
            results.append({"project": target_name, "slug": slug, "status": "queued"})
        except Exception as e:
            results.append({"project": target_name, "status": "failed", "error": str(e)[:100]})

    return results


def run():
    """Periodic: check recent merges for propagation opportunities."""
    if not PROPAGATION_ENABLED:
        print("[propagation] disabled")
        return

    # Look at recent MERGED tasks in the last hour
    try:
        recent = db.select("tasks", {
            "select": "id,prompt,project_id,kind,slug,state,note",
            "state": "eq.MERGED",
            "order": "finished_at.desc",
            "limit": 10,
        }) or []
    except Exception:
        print("[propagation] failed to fetch recent merges")
        return

    propagated = 0
    for t in recent:
        # Skip already-propagated tasks
        if "propagated" in (t.get("note") or "").lower():
            continue
        if "prop-" in (t.get("slug") or ""):
            continue

        # Get project name
        try:
            proj = db.select("projects", {"select": "name", "id": f"eq.{t['project_id']}"})
            project_name = proj[0]["name"] if proj else "unknown"
        except Exception:
            continue

        results = propagate(t, project_name, [], "")
        if results:
            propagated += sum(1 for r in results if r.get("status") == "queued")
            # Mark as propagated
            try:
                note = t.get("note", "") or ""
                db.update("tasks", t["id"], {"note": f"{note} [propagated to {len(results)} projects]"})
            except Exception:
                pass

    print(f"[propagation] scanned {len(recent)} recent merges, propagated {propagated} tasks")
