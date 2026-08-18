#!/usr/bin/env python3
"""Cross-project patch transplant hints before model spend."""
import os
import sys
import re
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_diff_library
import db
# ONE similarity floor (Wave C, Part 4). This module used to carry two: an env-defaulted 0.18
# in hint() and a hardcoded 0.25 in find_transplant_source(), neither of them the 0.55 the
# spec calls for. At 0.18 the "proven patch" handed to a coder is barely related to the task —
# that is where "adapt the proven patch beethoven/deployfix-… similarity=0.309" prompts come
# from, and adapting an unrelated diff is worse than starting clean.
import transplant_discipline


MARK = "PATCH TRANSPLANT"


def hint(task):
    if MARK in str(task.get("prompt") or ""):
        return ""
    hits = merged_diff_library.find(task, limit=1)
    if not hits:
        return ""
    h = hits[0]
    # Merge note: master read `similarity` here and gated on the env-defaulted
    # 0.18 floor. This branch replaced that with transplant_discipline, whose
    # whole point is ONE floor (0.55) — so the union keeps master's `similarity`
    # binding (the hint text below interpolates it) and this branch's gate.
    #
    # The 0.18 fallback is deliberately NOT reinstated: the rationale above says
    # a barely-related "proven patch" is worse than starting clean, so if the
    # discipline module cannot answer we emit no hint at all rather than
    # silently reverting to the weaker floor. Fail closed.
    similarity = h.get("similarity", 0)
    try:
        admissible = transplant_discipline.transplant_admissible(similarity)
    except Exception:
        admissible = False
    if not admissible:
        return ""
    return (f"{MARK}: before drafting from scratch, adapt the proven patch "
            f"{h.get('project', '?')}/{h.get('slug', '?')} (similarity {similarity}).\n"
            f"Prior intent: {h.get('summary', '')}\n"
            f"Relevant prior diff excerpt:\n{(h.get('diff') or '')[:2500]}")


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


def find_transplant_source(target_task, min_similarity=None):
    """Find prior patch with similarity >= min_similarity for transplant.

    `min_similarity` defaults to the single fleet-wide floor rather than the old hardcoded
    0.25, so this path and hint() can no longer disagree about what "similar enough" means.
    """
    if min_similarity is None:
        min_similarity = transplant_discipline.MIN_TRANSPLANT_SIMILARITY
    try:
        rows = db.select("patch_history", {})
        if not rows:
            return None
        for row in rows:
            if transplant_discipline.transplant_admissible(row.get("similarity"),
                                                           floor=min_similarity):
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

    was_bytes = isinstance(prior_diff, bytes)
    adapted = prior_diff
    if isinstance(adapted, bytes):
        adapted = adapted.decode("utf-8", errors="replace")

    if target_files:
        # Rewrite headers only when the diff targets none of the requested
        # files; rewriting per-file would clobber earlier matches.
        current_files = re.findall(r"--- a/(\S+)", adapted)
        already_targeted = any(
            cf in target_files or os.path.basename(cf) in target_files
            for cf in current_files
        )
        if not already_targeted:
            target_file = target_files[0]
            adapted = re.sub(r"--- a/\S+", f"--- a/{target_file}", adapted)
            adapted = re.sub(r"\+\+\+ b/\S+", f"+++ b/{target_file}", adapted)

    if "ORCH_PIPELINE_SECURITY_GATE" in adapted and "ORCH_" not in adapted.split("ORCH_PIPELINE_SECURITY_GATE")[0][-100:]:
        pass

    if was_bytes:
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
