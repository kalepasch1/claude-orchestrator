#!/usr/bin/env python3
"""Reusable patch templates for queued tasks.

Before agentic coding starts, turn the task intent and nearest merged diffs into
a compact scaffold. The scaffold is also stored best-effort for future reuse.

Branch recovery: if the task's branch is missing or stale when pre_claim_hook
is called, recovery is attempted via patch_recovery before the template is built.
"""
import hashlib
import importlib
import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Optional collaborators. Every one of these was a FUNCTION-LOCAL `import X`
# inside the function that used it, which cost two things:
#
#   1. `patch("patch_templates.merged_diff_library.find", ...)` and
#      `patch.object(patch_templates, "merged_diff_library", None)` both need a
#      module ATTRIBUTE to bind to. A function-local import creates a local
#      name, so the patch target never existed and the two tests that exercise
#      the fail-soft branches of build() could not run at all — the same defect
#      already fixed in runner/tdd_gate.py.
#   2. An import failure was re-paid on every single call instead of once.
#
# They stay OPTIONAL: if one is absent the name is None, the call raises
# AttributeError, and each call site's existing handler degrades exactly as it
# did when the import itself was the thing that raised. No cycle exists — none
# of these five pulls patch_templates back in (verified 2026-08-26).


def _optional(module_name):
    """Import MODULE_NAME, or None when it is not installed.

    One handler that RETURNS a default, rather than five module-level
    `try/except ImportError: X = None` blocks that can only assign one — the
    shape convention-lint's FAIL_SOFT_ERROR rule exists to discourage, and here
    it is right: a helper says "absent is an ordinary outcome" once instead of
    five times.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


merged_diff_library = _optional("merged_diff_library")   # absent: build() emits "none found"
patch_adaptation = _optional("patch_adaptation")         # absent: summaries, no structure
merged_diff_adapter = _optional("merged_diff_adapter")   # absent: structure, no file scaffold
patch_recovery = _optional("patch_recovery")             # absent: a missing branch stays missing
savings_meter = _optional("savings_meter")               # absent: template still built and stored

log = logging.getLogger(__name__)

MARK = "[patch-template:"
WORD = re.compile(r"[a-z0-9_]{4,}", re.I)
SYMBOL_HINT = re.compile(r"\b(?:api|route|component|hook|schema|migration|webhook|test|store|model|auth|cache|worker)\b", re.I)


#: Identifier words that name a credential. Bounded with (?<![A-Za-z0-9]) rather
#: than \b because \b treats "_" as a word character, which would match a bare
#: SECRET while missing DATABASE_PASSWORD and STRIPE_SECRET_KEY — the shapes real
#: prompts actually use. Same reasoning as tools/convention_lint.py.
_SECRET_WORD = (
    r"(?<![A-Za-z0-9])(?:pass(?:word|wd)?|secret|token|apikey|api[_-]?key"
    r"|private[_-]?key|access[_-]?key|auth|credential[s]?|bearer)(?![A-Za-z0-9])"
)

#: `NAME=value`, `NAME: value` or `NAME value` where NAME names a credential.
#: The VALUE is what leaks, so the whole pair goes.
_SECRET_ASSIGNMENT = re.compile(_SECRET_WORD + r"\s*[:=]\s*\S+", re.I)

#: A PEM private key block, which is self-identifying and never belongs in a
#: reusable template.
_PEM_BLOCK = re.compile(
    r"-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*PRIVATE KEY-----",
    re.I | re.DOTALL)

#: The bare credential noun on its own, so "database password" does not survive
#: into the keyword index even when no value followed it.
_SECRET_BARE = re.compile(_SECRET_WORD, re.I)


def _redact(text):
    """Remove credential-shaped content from a prompt before it is stored.

    WHY (2026-08-26). _words() lifted every word of five characters or more
    straight out of the raw prompt, and those words become two things that
    OUTLIVE the task: the "Intent:" line of the template body, and the keyword
    list the template store indexes on. Templates are persisted best-effort and
    reused across tasks, so a prompt reading "Fix database with
    PASSWORD=secret123" put `secret123` into a shared, searchable store.

    runner/test_patch_templates_security.py has asserted against exactly this
    since it was written — test_build_body_sanitizes_intent_not_raw_prompt and
    test_template_keywords_are_safe_for_indexing, both red. The sanitisation was
    specified and tested and never implemented.

    Redaction is deliberately blunt: a lost intent word costs a slightly weaker
    template, a leaked one costs a credential in a shared store.
    """
    body = str(text or "")
    body = _PEM_BLOCK.sub(" ", body)
    body = _SECRET_ASSIGNMENT.sub(" ", body)
    return _SECRET_BARE.sub(" ", body)


def _words(text):
    return sorted({w.lower() for w in WORD.findall(_redact(text)) if len(w) > 4})[:80]


def _intent(task):
    prompt = _redact((task or {}).get("prompt"))
    return {"words": _words(prompt), "hints": sorted(set(m.group(0).lower() for m in SYMBOL_HINT.finditer(prompt)))}


def _id(task):
    raw = json.dumps({"slug": task.get("slug"), "intent": _intent(task)}, sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def build(task):
    tid = _id(task)
    prompt = str(task.get("prompt") or "")
    hits = []
    try:
        hits = merged_diff_library.find(task, limit=2)
    except Exception:
        hits = []
    # The slug leads the Intent line. Without it the body named the task
    # NOWHERE — only a 12-hex tid — so a template pulled back out of the
    # knowledge table or the JSONL store could not be attributed to the work it
    # was built from, and the agent reading the scaffold was told what words the
    # prompt used but not what the task was called. It is deliberately NOT run
    # through _redact(): a slug is a queue identifier, not free text, and it is
    # already stored verbatim as the knowledge row's title and the JSONL "task"
    # field. Redacting it here while storing it in the clear one call later
    # would cost lookups and buy nothing. It leads the line rather than taking a
    # line of its own because the body's line ORDER is pinned by
    # runner/tests/test_patch_templates_behavioral_equivalence.py.
    _intent_words = " ".join(_intent(task)["words"][:24])
    _slug = str(task.get("slug") or "").strip()
    lines = [
        f"PATCH TEMPLATE {tid}",
        "Intent: " + (f"{_slug} — {_intent_words}" if _slug else _intent_words),
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
            adapted = patch_adaptation.directive(task, hits, target_hint=task.get("slug") or tid)
            if adapted:
                lines.append(adapted)
        except Exception as exc:  # fail-soft: a bad hit must not break template build
            log.debug("patch_templates: adaptation skipped (%s)", exc)
        # Complements the structural directive above: that one says HOW the prior
        # patch was shaped, this one says WHICH files and line ranges it touched.
        # Both are fail-soft — no adapter, no scaffold, same template as before.
        try:
            scaffold = merged_diff_adapter.adapt(hits, target_files=task.get("target_files"))
        except Exception as exc:
            log.debug("patch_templates: diff scaffold skipped (%s)", exc)
            scaffold = ""
        if scaffold:
            lines.append(scaffold)
    else:
        lines.append("Prior merged patterns to adapt: none found; keep the patch template reusable.")
    return tid, "\n".join(lines)


def _fallback_path():
    """Local JSONL store used when the knowledge table is unavailable."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".runtime", "patch_templates.jsonl")


def _body_declares(body, tid):
    """True only when `body`'s header names EXACTLY this template id.

    The knowledge query is a PREFIX filter (`like.PATCH TEMPLATE <tid>*`) and the
    old confirmation was `tid in body`, so both halves were prefix matches: asking
    for a partial id — or for an id that happens to be a prefix of another —
    returned a DIFFERENT task's template body, relabelled with the id that was
    asked for. Ids are 12-hex digests today, which hid it; a caller holding a
    truncated id is all it takes. The stored body's first line is
    "PATCH TEMPLATE <tid>" (see build()), so compare that line exactly.
    """
    first_line = str(body or "").split("\n", 1)[0].strip()
    return first_line == f"PATCH TEMPLATE {tid}"


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
            if _body_declares(body, tid):
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


#: Entries retained in the local JSONL fallback. It is append-only and BOTH `lookup()`
#: and `find_template()` scan it end to end, so without a bound it is a slow leak with an
#: O(n) read on the dependency-recovery path — the same reasoning CLAUDE.md gives for
#: bounding the diff cache. ORCH_-prefixed so it is fleet-pushable via fleet_control.py.
FALLBACK_MAX_ENTRIES = max(1, int(os.environ.get("ORCH_PATCH_TEMPLATE_FALLBACK_MAX", "500")))


def _prune_fallback(path, keep=None):
    """Trim the local store to its newest `keep` entries. True if it was rewritten.

    Newest-wins is the existing read semantics — `find_template` takes the LAST matching
    line — so pruning from the FRONT preserves exactly what a reader would have returned.
    Fail-soft: any error leaves the file untouched and returns False. A failed prune must
    never lose a template; an oversized file is a slow problem, a truncated one is not.
    """
    keep = FALLBACK_MAX_ENTRIES if keep is None else max(1, int(keep))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return False
    if len(lines) <= keep:
        return False
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(lines[-keep:])
        os.replace(tmp, path)   # atomic: a crash mid-prune cannot leave a half file
        log.info("patch_templates: pruned local store %d -> %d entries",
                 len(lines), keep)
        return True
    except OSError as exc:
        log.warning("patch_templates: could not prune %s (%s); leaving it intact",
                    path, exc)
        try:
            os.unlink(path + ".tmp")
        except OSError:
            pass
        return False


def _store(task, template_id, body):
    row = {"project": task.get("project_id") or "unknown",
           "title": f"patch template {task.get('slug') or template_id}",
           "body": body,
           "keywords": _intent(task)["words"],
           "tags": ["patch-template", task.get("kind") or "build"],
           "created_at": "now()"}
    try:
        db.insert("knowledge", row, upsert=True)
    except Exception as exc:
        path = _fallback_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as f:
                f.write(json.dumps({"ts": time.time(), "task": task.get("slug"),
                                    "template_id": template_id, "body": body}) + "\n")
            # SAY SO. A template that reached only local disk is invisible to every
            # other host, so a recovery pass on another Mac will not find it and will
            # rebuild the work. Silently succeeding here is what makes that undetectable.
            log.warning("patch_templates: knowledge write failed (%s); template %s for "
                        "%s is LOCAL-ONLY at %s and invisible to other hosts",
                        exc, template_id, task.get("slug"), path)
            _prune_fallback(path)
        except OSError:
            pass


def inject_prompt(task):
    """Prepend a patch-template scaffold to TASK's prompt. Fail-soft: never raises.

    WHY the guard (2026-08-26). A patch template is an OPTIMISATION — it hands
    the coding agent a scaffold it would otherwise reconstruct. It is never the
    work itself. `build()` reaches out to merged_diff_library, patch_adaptation
    and merged_diff_adapter, each of which can touch the control plane, so
    "the scaffold could not be built" is an ordinary outcome, not an error.

    Unguarded, that ordinary outcome propagated out of inject_prompt and killed
    the task it was supposed to help: a template lookup failure meant the task
    never ran at all. `pre_claim_hook` — the same wrapper one function below,
    doing the same job on the same body — has always had `except Exception:
    return task`. This one simply never got it. The contract both should honour
    is the obvious one: no scaffold, run the task on its own prompt.
    """
    prompt = str((task or {}).get("prompt") or "")
    if MARK in prompt:
        return task
    try:
        template_id, body = build(task)
    except Exception as exc:  # fail-soft: no scaffold must not mean no task
        log.debug("patch_templates: template build failed for %s (%s) — "
                  "running the task on its own prompt",
                  (task or {}).get("slug") or "?", exc)
        return task
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
