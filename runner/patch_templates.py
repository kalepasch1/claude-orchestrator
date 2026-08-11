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

#: The two kinds of thing `lookup` can hand back. A SCAFFOLD is prose — an
#: intent line and three implementation slots. A DIFF carries applicable hunks.
#: They are not interchangeable and callers must not treat them as such.
KIND_DIFF = "diff"
KIND_SCAFFOLD = "scaffold"

#: Appended by `build()` when every cited prior pattern turns out to be prose.
#: Named rather than inlined so a planner or test can match on it exactly.
NO_DIFF_NOTE = (
    "NOTE: none of the patterns above contain a diff. They are scaffolds. "
    "Do not plan work that applies, integrates, or rebases them as patches — "
    "read them as intent and write the change yourself."
)


#: Last-resort copy of `patch_template_apply._DIFF_MARKERS`. This duplication is
#: deliberate and must stay: the fallback exists precisely for the case where
#: that module cannot be imported, so it cannot import the constant either.
_FALLBACK_DIFF_MARKERS = ("diff --git ", "--- ", "+++ ", "@@ ")


def _looks_like_diff(text):
    """True when `text` plausibly contains unified-diff hunks.

    Delegates to `patch_template_apply.looks_like_diff`, which is the repo's one
    diff detector — do not add a second. Fail-soft: if that module cannot be
    imported (it pulls in subprocess/git helpers), fall back to the same marker
    scan rather than raising, since classification must never wedge a lookup.
    """
    try:
        from patch_template_apply import looks_like_diff
        return looks_like_diff(text)
    except Exception:
        if not isinstance(text, str) or not text:
            return False
        return any(marker in text for marker in _FALLBACK_DIFF_MARKERS)


def classify_body(body):
    """Classify a template body as KIND_DIFF or KIND_SCAFFOLD.

    WHY THIS EXISTS
    ---------------
    `build()` never emits a diff. It emits a prose scaffold, and its "Prior
    merged patterns to adapt" section splices in the *body text* of other
    scaffolds — so a scaffold can quote another scaffold verbatim and read, to a
    downstream planner, exactly like a stored patch.

    That misreading is expensive and has already happened. The
    `dropbox-beethoven-audit-addendum-two-session-recon-slice-1` family was
    decomposed into slices instructing an agent to "integrate the two adapted
    diffs bffd1c2752f8 and 7ba77da91bb4" and to resolve their merge conflicts.
    Neither template contains a single hunk; both are scaffolds quoting a third
    scaffold. The slices could not succeed, and the family churned through
    DECOMPOSED / SUPERSEDED / QUARANTINED states up to attempt 43 before hitting
    the repair ceiling.

    Callers that are about to spawn "apply/integrate/rebase this diff" work
    should ask `carries_diff()` first and plan differently for a scaffold.
    """
    return KIND_DIFF if _looks_like_diff(body) else KIND_SCAFFOLD


def _body_of(template):
    """Coerce a lookup() dict, a body string, or a template id to a body string.

    A plain string is ambiguous — it may be the body itself or just the twelve-hex
    id that names it. Resolve that once, here, so callers do not each guess:
    if the string already reads as a diff it *is* the body; otherwise treat it as
    an id and resolve it. Anything else (None, int, list) has no body.
    """
    if isinstance(template, dict):
        return template.get("body")
    if isinstance(template, str):
        return template if _looks_like_diff(template) else (lookup(template) or {}).get("body")
    return None


def carries_diff(template):
    """True when a template id, body string, or lookup() dict holds real hunks.

    Accepts whichever form the caller already has, so nobody has to re-resolve a
    template just to ask this question. Fail-soft: unknown ids answer False,
    which is the safe direction — refusing to spawn diff work for a template
    that turns out to have a diff costs one planning pass, while spawning it for
    a scaffold costs the loop described in `classify_body`.
    """
    return classify_body(_body_of(template)) == KIND_DIFF


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
        # Label every cited pattern with whether it actually carries hunks. A hit
        # whose summary is another scaffold reads like a patch and is not one;
        # saying so inline is what stops a planner slicing this into
        # "integrate the adapted diff" work that has nothing to integrate.
        # Classify once per hit — carries_diff may hit the template store.
        labelled = [(h, carries_diff(h.get("summary"))) for h in hits]
        lines.append("Prior merged patterns to adapt:")
        for hit, is_diff in labelled:
            tag = "diff" if is_diff else "scaffold — prose only, no diff to apply"
            lines.append(
                f"- [{tag}] {hit.get('project')}/{hit.get('slug')} "
                f"sim={hit.get('similarity')}: {hit.get('summary')}"
            )
        if not any(is_diff for _, is_diff in labelled):
            lines.append(NO_DIFF_NOTE)
    else:
        lines.append("Prior merged patterns to adapt: none found; keep the patch template reusable.")
    return tid, "\n".join(lines)


def _fallback_path():
    """Local JSONL store used when the knowledge table is unavailable."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".runtime", "patch_templates.jsonl")


def _classified(row):
    """Attach `kind`/`carries_diff` to a resolved row, without dropping keys.

    Existing callers read `body`, `title`, `source` and `template_id`; those are
    untouched. The two new keys are additive so a caller can tell a scaffold from
    a real patch without re-parsing the body itself.
    """
    if not isinstance(row, dict) or not row:
        return {}
    kind = classify_body(row.get("body"))
    return {**row, "kind": kind, "carries_diff": kind == KIND_DIFF}


def lookup(template_id):
    """Resolve a stored patch template by id. Fail-soft: returns {} on any miss/error.

    Checks the local JSONL fallback first (newest matching entry wins), then
    falls back to a best-effort knowledge-table query.

    The returned dict additionally carries `kind` (`KIND_DIFF`/`KIND_SCAFFOLD`)
    and `carries_diff`. Most stored templates are scaffolds — prose, no hunks —
    so a caller planning to apply the result must check before treating it as a
    patch. See `classify_body` for what that mistake has already cost.
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
        return _classified(found)
    try:
        rows = db.select("knowledge", {"select": "title,body,tags",
                                       "body": f"like.PATCH TEMPLATE {tid}*"})
        for row in rows or []:
            body = str((row or {}).get("body") or "")
            if tid in body:
                return _classified({"template_id": tid, "body": body,
                                    "title": (row or {}).get("title"), "source": "db"})
    except Exception:
        pass
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
