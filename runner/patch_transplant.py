#!/usr/bin/env python3
"""Cross-project patch transplant hints before model spend."""
import os
import sys

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
