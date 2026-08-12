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
        # Summaries alone make the coder reread the whole prior diff. Extract the
        # reusable structure (helpers, owner dirs, test layout, naming) instead.
        try:
            import patch_adaptation
            adapted = patch_adaptation.directive(task, hits, target_hint=task.get("slug") or tid)
            if adapted:
                lines.append(adapted)
        except Exception as exc:  # fail-soft: a bad hit must not break template build
            log.debug("patch_templates: adaptation skipped (%s)", exc)
    else:
        lines.append("Prior merged patterns to adapt: none found; keep the patch template reusable.")
    return tid, "\n".join(lines)


def _fallback_path():
    """Local JSONL store used when the knowledge table is unavailable."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".runtime", "patch_templates.jsonl")


def lookup(template_id):
    """Resolve a stored patch template by id. Fail-soft: returns {} on any miss/error.

    Checks the local JSONL fallback first (newest matching entry wins), then
    falls back to a best-effort knowledge-table query.
    """
    tid = str(template_id or "").strip()
    if not tid:
        return {}
    found = {}
    try:
        with open(_fallback_path()) as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("template_id") == tid:
                    found = row
    except OSError:
        pass
    if found:
        return found
    try:
        rows = db.select("knowledge", {"select": "title,body,tags",
                                       "body": f"like.PATCH TEMPLATE {tid}*"})
        for row in rows or []:
            body = str((row or {}).get("body") or "")
            if tid in body:
                return {"template_id": tid, "body": body,
                        "title": (row or {}).get("title"), "source": "db"}
    except Exception:
        pass
    return {}


def find_template(slug):
    """Resolve a reusable patch for a task SLUG. Fail-soft: {} on any miss/error.

    `lookup()` resolves by template id; this resolves by slug, which is what the
    callers that hold a dependency name actually have. `dependency_stub`
    already called this function behind `hasattr(patch_templates, ...)` — the
    attribute never existed, so its patch-template recovery path had been dead
    code since it was written. It applies `template["diff"]`, so an APPLICABLE
    hit must carry one:

      * `merged_diffs` (newest matching row wins) yields a real diff and IS
        applicable — the key is present.
      * the local JSONL patch-template store yields only a scaffold body, so no
        `diff` key is set and the caller's `template.get("diff")` guard makes it
        a clean no-op rather than a bogus `git apply`.
    """
    name = str(slug or "").strip()
    if not name:
        return {}
    try:
        rows = db.select("merged_diffs", {"select": "slug,project,kind,diff,files,created_at",
                                          "slug": f"eq.{name}",
                                          "order": "created_at.desc", "limit": "1"}) or []
        for row in rows:
            diff = str((row or {}).get("diff") or "")
            if diff.strip():
                return {"slug": name, "diff": diff, "project": (row or {}).get("project"),
                        "files": (row or {}).get("files") or [], "source": "merged_diffs"}
    except Exception as exc:  # fail-soft: a DB outage must not break dependency recovery
        log.debug("patch_templates: merged_diffs lookup failed for %s (%s)", name, exc)
    found = {}
    try:
        with open(_fallback_path()) as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("task") == name:
                    found = row
    except OSError:
        pass
    if found:
        return {"slug": name, "template_id": found.get("template_id"),
                "body": found.get("body") or "", "source": "jsonl"}
    return {}


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
        path = _fallback_path()
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
    """FIXED 2026-07-11: removed db.update() that permanently corrupted prompts."""
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
