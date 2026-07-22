#!/usr/bin/env python3
"""Reusable patch templates for queued tasks.

Before agentic coding starts, turn the task intent and nearest merged diffs into
a compact scaffold. The scaffold is also stored best-effort for future reuse.

Branch recovery: if the task's branch is missing or stale when pre_claim_hook
is called, recovery is attempted via patch_recovery before the template is built.
"""
import hashlib
import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

log = logging.getLogger(__name__)

MARK = "[patch-template:"
WORD = re.compile(r"[a-z0-9_]{4,}", re.I)
SYMBOL_HINT = re.compile(r"\b(?:api|route|component|hook|schema|migration|webhook|test|store|model|auth|cache|worker)\b", re.I)


def _words(text):
    return sorted({w.lower() for w in WORD.findall(str(text or "")) if len(w) > 4})[:80]


def _intent(task):
    prompt = str((task or {}).get("prompt") or "")
    return {"words": _words(prompt), "hints": sorted(set(m.group(0).lower() for m in SYMBOL_HINT.finditer(prompt)))}


def _id(task):
    raw = json.dumps({"slug": task.get("slug"), "intent": _intent(task)}, sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def build(task):
    tid = _id(task)
    prompt = str(task.get("prompt") or "")
    hits = []
    try:
        import merged_diff_library
        hits = merged_diff_library.find(task, limit=2)
    except Exception:
        hits = []
    lines = [
        f"PATCH TEMPLATE {tid}",
        "Intent: " + " ".join(_intent(task)["words"][:24]),
        "Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.",
        "Implementation slots:",
        "1. Locate the existing owner module/function before adding new files.",
        "2. Reuse matching project helpers and naming conventions.",
        "3. Add or update the narrowest test/check that proves the requested behavior.",
    ]
    if hits:
        lines.append("Prior merged patterns to adapt:")
        for h in hits:
            lines.append(f"- {h.get('project')}/{h.get('slug')} sim={h.get('similarity')}: {h.get('summary')}")
    else:
        lines.append("Prior merged patterns to adapt: none found; keep the patch template reusable.")
    return tid, "\n".join(lines)


def _store(task, template_id, body):
    row = {"project": task.get("project_id") or "unknown",
           "title": f"patch template {task.get('slug') or template_id}",
           "body": body,
           "keywords": _intent(task)["words"],
           "tags": ["patch-template", task.get("kind") or "build"],
           "created_at": "now()"}
    try:
        db.insert("knowledge", row, upsert=True)
    except Exception:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".runtime", "patch_templates.jsonl")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as f:
                f.write(json.dumps({"ts": time.time(), "task": task.get("slug"),
                                    "template_id": template_id, "body": body}) + "\n")
        except OSError:
            pass


def inject_prompt(task):
    prompt = str((task or {}).get("prompt") or "")
    if MARK in prompt:
        return task
    template_id, body = build(task)
    new_prompt = body + f"\n{MARK}{template_id}]\n\n" + prompt
    return {**task, "prompt": new_prompt}


def _get_project(project_id):
    """Fetch project row for repo_path and default_base. Returns dict or None."""
    if not project_id:
        return None
    try:
        rows = db.select("projects", {"select": "id,name,repo_path,default_base",
                                      "id": f"eq.{project_id}"})
        return (rows or [None])[0]
    except Exception:
        return None


def _ensure_branch(task):
    """Detect missing branch and attempt recovery. Fail-soft: never raises."""
    try:
        import patch_recovery
        slug = task.get("slug") or ""
        if not slug:
            return
        proj = _get_project(task.get("project_id"))
        repo = (proj or {}).get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            return
        base = task.get("base_branch") or (proj or {}).get("default_base") or "main"

        detection = patch_recovery.detect_branch(repo, slug)
        if detection["found"]:
            return

        # Branch missing — attempt mechanical recovery before the template is built
        intent_words = _words(task.get("prompt") or "")
        template_id = _id(task)

        # Try patch-first recovery (stored patch → reflog → template adaptation)
        result = patch_recovery.recover(repo, slug, base, project=task.get("project_id"))
        if result["ok"]:
            log.info("patch_templates: branch recovered via %s for %s", result["method"], slug)
            return

        # Fall back to regeneration from intent (cache replay → intent stub)
        result = patch_recovery.regenerate_from_intent(
            repo, slug, base, intent_words, template_id=template_id
        )
        if result["ok"]:
            log.info("patch_templates: branch regenerated via %s for %s", result["method"], slug)
        else:
            log.warning(
                "patch_templates: branch recovery failed for %s (%s) — "
                "suggest re-scoping or manual intervention",
                slug, result.get("reason", "unknown"),
            )
    except Exception as exc:
        log.debug("patch_templates._ensure_branch: %s", exc)


def pre_claim_hook(task):
    """Inject patch template into the in-memory task dict for the current run.

    FIXED 2026-07-11: previously wrote the mutated prompt back to the DB via
    db.update(), permanently corrupting the original prompt.  Tasks that failed
    and retried accumulated layers of PATCH TEMPLATE boilerplate until the
    original instructions were buried under hex-hash keyword salad.  1,801 tasks
    were quarantined as unexecutable garbage from this bug.

    Now: template is prepended in-memory only — the DB prompt stays clean.
    """
    try:
        if not isinstance(task, dict) or MARK in str(task.get("prompt") or ""):
            return task
        _ensure_branch(task)
        template_id, body = build(task)
        new_prompt = body + f"\n{MARK}{template_id}]\n\n" + str(task.get("prompt") or "")
        # DO NOT write back to DB — keep original prompt intact for retries
        _store(task, template_id, body)
        try:
            import savings_meter
            savings_meter.record("patch_template", prompt=str(task.get("prompt") or ""),
                                 result_text=body, detail=f"template={template_id}")
        except Exception:
            pass
        return {**task, "prompt": new_prompt}
    except Exception:
        return task


if __name__ == "__main__":
    tid, text = build({"slug": "demo", "prompt": " ".join(sys.argv[1:])})
    print(text)
