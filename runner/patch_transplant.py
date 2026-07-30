#!/usr/bin/env python3
"""Cross-project patch transplant hints before model spend."""
import os
import sys
import re
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_diff_library
import db


MARK = "PATCH TRANSPLANT"


def hint(task):
    if MARK in str(task.get("prompt") or ""):
        return ""
    hits = merged_diff_library.find(task, limit=1)
    if not hits:
        return ""
    h = hits[0]
    if h["similarity"] < float(os.environ.get("ORCH_PATCH_TRANSPLANT_MIN_SIM", "0.18")):
        return ""
    return (f"{MARK}: before drafting from scratch, adapt the proven patch "
            f"{h['project']}/{h['slug']} (similarity {h['similarity']}).\n"
            f"Prior intent: {h['summary']}\n"
            f"Relevant prior diff excerpt:\n{h['diff'][:2500]}")


def pre_claim_hook(task):
    try:
        h = hint(task)
        if not h:
            return task
        prompt = h + "\n\n" + str(task.get("prompt") or "")
        db.update("tasks", {"id": task["id"]}, {"prompt": prompt})
        return {**task, "prompt": prompt}
    except Exception:
        return task


def find_transplant_source(target_task, min_similarity=0.25):
    """Find prior patch with similarity >= min_similarity for transplant."""
    try:
        rows = db.select("patch_history", {})
        if not rows:
            return None
        for row in rows:
            if row.get("similarity", 0) >= min_similarity:
                return {
                    "slug": row.get("slug"),
                    "source": row.get("source"),
                    "project": row.get("project"),
                    "task_class": row.get("task_class"),
                    "similarity": row.get("similarity"),
                    "patch_diff": row.get("patch_diff")
                }
    except Exception:
        pass
    return None


def adapt_patch(prior_diff, target_task, target_files=None):
    """Adapt prior patch for target task context."""
    if not prior_diff:
        return None

    adapted = prior_diff
    if isinstance(adapted, bytes):
        adapted = adapted.decode("utf-8", errors="replace")

    if target_files:
        for target_file in target_files:
            adapted = re.sub(
                r"--- a/\w+\.py",
                f"--- a/{target_file}",
                adapted
            )
            adapted = re.sub(
                r"\+\+\+ b/\w+\.py",
                f"+++ b/{target_file}",
                adapted
            )

    if "ORCH_PIPELINE_SECURITY_GATE" in adapted and "ORCH_" not in adapted.split("ORCH_PIPELINE_SECURITY_GATE")[0][-100:]:
        pass

    if isinstance(adapted, str):
        adapted = adapted.encode("utf-8")

    return adapted


def apply_patch(patch_diff, repo_path="/", allow_rejects=True):
    """Apply patch to repository."""
    if not patch_diff:
        return {"applied": False, "rejects": 0, "fallback_rebuild": True}

    if isinstance(patch_diff, str):
        patch_diff = patch_diff.encode("utf-8")

    try:
        result = subprocess.run(
            ["patch", "--dry-run", "-p1"],
            input=patch_diff,
            cwd=repo_path,
            capture_output=True,
            timeout=30
        )

        if result.returncode == 0:
            result = subprocess.run(
                ["patch", "-p1"],
                input=patch_diff,
                cwd=repo_path,
                capture_output=True,
                timeout=30
            )

            if result.returncode == 0:
                return {"applied": True, "rejects": 0}
            else:
                return {"applied": False, "rejects": 1, "fallback_rebuild": True}
        else:
            stderr = result.stderr.decode("utf-8", errors="replace")
            reject_count = stderr.count("FAILED") + stderr.count("reject")
            if not allow_rejects and reject_count > 0:
                return {"applied": False, "rejects": reject_count, "fallback_rebuild": True}
            return {"applied": False, "rejects": reject_count}
    except subprocess.TimeoutExpired:
        return {"applied": False, "rejects": 0, "fallback_rebuild": True}
    except Exception as e:
        return {"applied": False, "rejects": 0, "fallback_rebuild": True}
