#!/usr/bin/env python3
"""Turn terminal blockers into safe, claimable rework.

auto_remediate handles normal retries. This module handles the rows that should
not be retried verbatim: legal, secret/security, no-op, missing-branch, and
repeat build/test failures. It parks the original row and creates a smaller,
safer replacement task that can flow through the normal coder/merge pipeline.
"""
import collections
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract
import privacy
import agentic_repair

DEFAULT_LIMIT = int(os.environ.get("ORCH_QUARANTINE_LIMIT", "120"))
MAX_BASE_CHARS = int(os.environ.get("ORCH_QUARANTINE_PROMPT_CHARS", "12000"))
MARK = "blocker-quarantine"
REPLACEMENT_CATEGORIES = {"legal", "secret", "security"}

_LEGAL = re.compile(
    r"\b(legal review|legal counsel|upl|unauthorized practice|regulatory|licen[cs]ing|"
    r"securities|broker[- ]dealer|investment advice|insurance|money transmission|"
    r"tax|cpa|filing|compliance opinion|practice of law)\b",
    re.I,
)
_SECRET = re.compile(
    r"\b(secret|api key|token|private key|credential|password|cron_secret|webhook secret|"
    r"hardcoded.*(?:key|secret|token)|leak)\b|\.claude/settings\.local\.json",
    re.I,
)
_SECURITY = re.compile(
    r"\b(security regression|rls|hmac|csrf|xss|sql injection|input validation|"
    r"broad allowlist|overbroad permission|sensitive log|unsafe fallback)\b",
    re.I,
)
_BUILD = re.compile(
    r"\b(buildfail|build red|production build red|command not found|cannot find module|"
    r"tsc|nuxt|nuxi|vite|next|prisma|vue-tsc|npm run build|yarn)\b",
    re.I,
)
_TEST = re.compile(r"\b(testfail|tests? failed|qa failed|verify failed|judge:|quality gate)\b", re.I)
_MISSING = re.compile(r"\b(missing branch|branch.*missing|no longer exists|approved.*agent/|recover-missing-branch)\b", re.I)
_NOOP = re.compile(r"\b(no committable|no file changes|changed nothing|empty diff|agent produced no)\b", re.I)
_EXHAUSTED = re.compile(r"\b(exhausted retries|remediation cap|blocked after \d+ auto-fixes|too large)\b", re.I)


def _norm_slug(text, fallback="task"):
    slug = re.sub(r"[^a-z0-9-]+", "-", str(text or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or fallback


def _replacement_slug(task, category):
    base = _norm_slug(task.get("slug") or task.get("id"))
    digest = hashlib.sha1(
        f"{task.get('id')}:{task.get('slug')}:{category}".encode("utf-8")
    ).hexdigest()[:7]
    prefix = f"rework-{_norm_slug(category)}-"
    room = max(12, 80 - len(prefix) - len(digest) - 1)
    return f"{prefix}{base[:room].strip('-')}-{digest}"[:80]


def _signal(task):
    return "\n".join(
        str(task.get(k) or "") for k in ("slug", "note", "log_tail", "prompt", "kind")
    )


def _clean_note_for_classification(note):
    text = str(note or "")
    if MARK in text and "Original blocker:" in text:
        return text.split("Original blocker:", 1)[1]
    return text


_REWORK_PREFIX = re.compile(r"^(?:rework-[a-z]+-)+", re.I)


def _blocker_signal(task):
    raw_slug = str(task.get("slug") or "")
    slug = _REWORK_PREFIX.sub("", raw_slug)
    note = _clean_note_for_classification(task.get("note"))
    log_tail = str(task.get("log_tail") or "")
    # strip the task's own full slug from evidence so the quarantine history embedded in branch
    # names / notes never re-triggers its own prior category on repair attempts
    if raw_slug:
        note = note.replace(raw_slug, "")
        log_tail = log_tail.replace(raw_slug, "")
    return "\n".join(
        (
            slug,
            note,
            log_tail,
            str(task.get("kind") or ""),
            str(task.get("state") or ""),
        )
    )


def classify(task):
    blocker = _blocker_signal(task)
    text = blocker + "\n" + str(task.get("prompt") or "")
    state = str(task.get("state") or "").upper()
    # Secret/security classification must come from the blocker evidence, not a broad prompt
    # word like an app name. Misclassifying QA failures as secret work makes agents fix the
    # wrong thing and slows the drain.
    if _SECRET.search(blocker):
        return "secret"
    if _SECURITY.search(blocker):
        return "security"
    if _LEGAL.search(text):
        return "legal"
    if _MISSING.search(text):
        return "missing-branch"
    if _BUILD.search(text):
        return "buildfail"
    if state == "TESTFAIL" or _TEST.search(text):
        return "testfail"
    if _NOOP.search(text):
        return "noop"
    if _EXHAUSTED.search(text):
        return "oversized"
    return "rework"


_REPLACEMENT_NOTE = re.compile(r"replacement for (?P<slug>.+?) category=(?P<category>[a-z-]+)", re.I)


def repair_misclassified(limit=300):
    """Correct replacement prompts created before classifier improvements.

    This is deliberately conservative: only QUEUED quarantine replacement rows are edited, and
    only their prompt/note/category metadata changes. The original quarantined row remains parked.
    """
    if os.environ.get("ORCH_QUARANTINE_REPAIR", "true").lower() not in ("1", "true", "yes", "on"):
        return {"checked": 0, "repaired": 0}
    rows = db.select(
        "tasks",
        {"select": "id,slug,note,state,project_id,base_branch,kind",
         "state": "eq.QUEUED", "order": "updated_at.desc", "limit": str(limit)},
    ) or []
    checked = repaired = 0
    for row in rows:
        note = str(row.get("note") or "")
        if not note.startswith(f"{MARK}: replacement"):
            continue
        m = _REPLACEMENT_NOTE.search(note)
        if not m:
            continue
        checked += 1
        old_category = m.group("category")
        orig_slug = m.group("slug")
        orig_rows = db.select(
            "tasks",
            {"select": "id,slug,prompt,note,log_tail,state,kind,project_id,base_branch,material",
             "slug": f"eq.{orig_slug}", "limit": "1"},
        ) or []
        if not orig_rows:
            continue
        orig = orig_rows[0]
        new_category = classify(orig)
        if new_category == old_category:
            continue
        patch = {
            "prompt": _replacement_prompt(orig, new_category, row.get("slug")),
            "note": f"{MARK}: replacement for {orig_slug} category={new_category}",
            "kind": "bugfix" if new_category in ("buildfail", "testfail", "missing-branch") else (orig.get("kind") or row.get("kind") or "build"),
            "force_coder": _forced_coder(new_category),
            "model": _forced_coder(new_category),
            "updated_at": "now()",
        }
        try:
            db.update("tasks", {"id": row["id"]}, patch)
            repaired += 1
        except Exception:
            continue
    return {"checked": checked, "repaired": repaired}


def dedupe_replacements(limit=1000):
    rows = db.select(
        "tasks",
        {"select": "id,slug,note,state,updated_at",
         "state": "eq.QUEUED", "order": "updated_at.desc", "limit": str(limit)},
    ) or []
    groups = collections.defaultdict(list)
    for row in rows:
        if str(row.get("note") or "").startswith(f"{MARK}: replacement"):
            groups[row.get("slug")].append(row)
    collapsed = 0
    for slug, items in groups.items():
        if len(items) <= 1:
            continue
        # Rows are already newest-first. Keep the newest replacement; park older duplicates.
        for dup in items[1:]:
            try:
                db.update("tasks", {"id": dup["id"]},
                          {"state": "DECOMPOSED", "account": None, "updated_at": "now()",
                           "note": f"{MARK}: duplicate replacement collapsed into {slug}"})
                collapsed += 1
            except Exception:
                continue
    return {"checked_slugs": len(groups), "collapsed": collapsed}


def _base_prompt(task):
    raw = task.get("prompt") or f"Implement the queued task '{task.get('slug')}'."
    base = pipeline_contract.original_request(raw).strip()
    if len(base) <= MAX_BASE_CHARS:
        return base
    head = min(3500, MAX_BASE_CHARS // 3)
    tail = MAX_BASE_CHARS - head
    return (
        base[:head].rstrip()
        + "\n\n[quarantine compaction: bulky middle context omitted. Inspect repo files and prior task notes directly.]\n\n"
        + base[-tail:].lstrip()
    )


def _category_directive(category):
    if category == "legal":
        return (
            "The original task was blocked by a legal/regulatory gate. Build a non-regulated safe "
            "variant of the same functional intent. Do not provide legal, tax, investment, insurance, "
            "or licensing advice; do not submit filings; do not make eligibility/recommendation "
            "decisions; do not custody, transmit, or execute transactions. Convert the feature into "
            "workflow support: intake, neutral education, draft/checklist generation, risk labeling, "
            "export/audit trail, and an explicit licensed-professional or owner approval gate. "
            "Acceptance: the product still helps the user progress, but all regulated execution is "
            "removed or gated behind human professional review."
        )
    if category in ("secret", "security"):
        return (
            "The original task was blocked by secret/security risk. Preserve the useful behavior while "
            "removing the unsafe mechanism. Do not commit secrets, tokens, credentials, broad local "
            "allowlists, or hardcoded fallback keys. Use environment-variable placeholders, validation, "
            "least-privilege config, safe defaults, scrubbed logs, and tests proving the unsafe path is "
            "closed."
        )
    if category == "buildfail":
        return (
            "This is a build-green recovery task. Fix only the source/config/dependency issue needed "
            "for the production build to pass. Reuse dependency prewarm/cache and avoid package-manager "
            "churn unless the detected repo setup requires it."
        )
    if category == "testfail":
        return (
            "This is a QA/test recovery task. Reproduce the failing check, make the smallest source or "
            "test update that satisfies the original intent, and leave the repo green."
        )
    if category == "missing-branch":
        return (
            "The prior branch is missing or stale. First try zero-spend recovery: inspect local branches, "
            "worktrees, merged-diff library, patch templates, and patch-transplant/cache hints. If no "
            "usable diff exists, regenerate the minimal patch from the original acceptance intent."
        )
    if category == "noop":
        return (
            "The previous attempt produced no committable changes. Re-scope into the smallest visible "
            "implementation that proves value in code, tests, config, or docs. Do not finish with only "
            "analysis."
        )
    if category == "oversized":
        return (
            "The task exhausted retries because it is too broad. Implement the first independently "
            "mergeable slice only, with clear acceptance checks. Leave later slices discoverable in the "
            "final note instead of broadening this patch."
        )
    return (
        "The original blocker should not be retried verbatim. Reconsider the strategy, preserve the "
        "functional value, remove the blocked mechanism, and implement the smallest mergeable safe variant."
    )


def _forced_coder(category):
    if category == "legal":
        return os.environ.get("ORCH_QUARANTINE_LEGAL_CODER") or os.environ.get("ORCH_QUARANTINE_CODER") or "ollama"
    if category in ("secret", "security"):
        return os.environ.get("ORCH_QUARANTINE_SECURITY_CODER") or os.environ.get("ORCH_QUARANTINE_CODER") or "ollama"
    return os.environ.get("ORCH_QUARANTINE_CODER") or os.environ.get("ORCH_QUARANTINE_FAST_CODER") or "ollama"


def _sensitivity(task, category):
    local_only = os.environ.get("ORCH_QUARANTINE_LOCAL_ONLY", "true").lower() in ("1", "true", "yes", "on")
    if local_only:
        return "crown_jewel"
    if category in ("secret", "security", "legal"):
        return "confidential"
    return privacy.sensitivity(_signal(task))


def _replacement_prompt(task, category, new_slug):
    note = (task.get("note") or task.get("log_tail") or "")[:1200]
    prompt = (
        f"{_base_prompt(task)}\n\n"
        "STRUCTURAL QUARANTINE REWORK\n"
        f"Original task: {task.get('slug')}\n"
        f"Replacement task: {new_slug}\n"
        f"Blocked category: {category}\n"
        f"Blocked context: {note}\n\n"
        f"{_category_directive(category)}\n\n"
        "Execution rules:\n"
        "- Prefer reuse before drafting: search existing repo helpers, merged-diff library, patch templates, and sibling patterns.\n"
        "- Keep the diff small and independently mergeable.\n"
        "- Run the relevant build/test/QA command and commit the patch.\n"
        "- Do not reintroduce the blocker that caused quarantine.\n"
    )
    if os.environ.get("ORCH_QUARANTINE_WRAP_PROMPT", "false").lower() not in ("1", "true", "yes", "on"):
        return prompt
    try:
        return pipeline_contract.wrap_prompt(
            prompt,
            project="",
            kind=task.get("kind") or "bugfix",
            source=MARK,
            slug=new_slug,
            material=False,
        )
    except Exception:
        return prompt


def _existing(slug):
    rows = db.select("tasks", {"select": "id,state", "slug": f"eq.{slug}", "limit": "1"}) or []
    return bool(rows)


def _insert_task(row):
    variants = [
        row,
        {k: v for k, v in row.items() if k != "sensitivity"},
        {k: v for k, v in row.items() if k not in ("sensitivity", "material")},
        {k: v for k, v in row.items() if k not in ("sensitivity", "material", "force_coder")},
        {k: v for k, v in row.items() if k not in ("sensitivity", "material", "force_coder", "deps")},
    ]
    for candidate in variants:
        try:
            db.insert("tasks", candidate)
            return True
        except Exception:
            continue
    return False


def _park_original(task, new_slug, category):
    note = (
        f"{MARK}: quarantined as {category}; replacement queued as {new_slug}. "
        f"Original blocker: {(task.get('note') or task.get('log_tail') or '')[:300]}"
    )[:900]
    patch = {"state": "QUARANTINED", "account": None, "updated_at": "now()", "note": note}
    try:
        db.update("tasks", {"id": task["id"]}, patch)
        return "QUARANTINED"
    except Exception:
        patch["state"] = "DECOMPOSED"
        db.update("tasks", {"id": task["id"]}, patch)
        return "DECOMPOSED"


def _repair_original(task, category):
    directive = _category_directive(category)
    patch = agentic_repair.repair_patch(task, _signal(task), category=category, directive=directive)
    patch["kind"] = "bugfix" if category in ("buildfail", "testfail", "missing-branch", "noop", "conflict") else (task.get("kind") or "build")
    db.update("tasks", {"id": task["id"]}, patch)


def _candidate_rows(limit):
    selects = [
        "id,slug,prompt,note,log_tail,state,kind,project_id,base_branch,material,remediation_count,model,force_coder,sensitivity",
        "id,slug,prompt,note,log_tail,state,kind,project_id,base_branch,material,remediation_count,model,force_coder",
        "id,slug,prompt,note,log_tail,state,kind,project_id,base_branch,material,remediation_count,model",
        "id,slug,prompt,note,log_tail,state,kind,project_id,base_branch,material",
        "id,slug,prompt,note,log_tail,state,kind,project_id,base_branch",
    ]
    last_err = None
    for select in selects:
        try:
            return db.select(
                "tasks",
                {
                    "select": select,
                    "state": "in.(BLOCKED,CONFLICT,TESTFAIL,SHELVED)",
                    "order": "updated_at.asc",
                    "limit": str(limit),
                },
            ) or []
        except Exception as e:
            last_err = e
            continue
    raise last_err


def run(limit=DEFAULT_LIMIT):
    if os.environ.get("ORCH_QUARANTINE_ENABLED", "true").lower() not in ("1", "true", "yes", "on"):
        return {"skipped": "disabled"}
    repaired = repair_misclassified(limit=int(os.environ.get("ORCH_QUARANTINE_REPAIR_LIMIT", "300")))
    deduped = dedupe_replacements(limit=int(os.environ.get("ORCH_QUARANTINE_DEDUPE_LIMIT", "1000")))
    rows = _candidate_rows(limit)
    created = parked = skipped = 0
    repaired_original = 0
    categories = collections.Counter()
    for task in rows:
        if MARK in str(task.get("note") or ""):
            skipped += 1
            continue
        category = classify(task)
        if category not in REPLACEMENT_CATEGORIES:
            try:
                _repair_original(task, category)
                repaired_original += 1
                categories[category] += 1
            except Exception:
                skipped += 1
            continue
        new_slug = _replacement_slug(task, category)
        if _existing(new_slug):
            _park_original(task, new_slug, category)
            parked += 1
            skipped += 1
            categories[category] += 1
            continue
        row = {
            "project_id": task.get("project_id"),
            "slug": new_slug,
            "state": "QUEUED",
            "kind": "bugfix" if category in ("buildfail", "testfail", "missing-branch") else (task.get("kind") or "build"),
            "prompt": _replacement_prompt(task, category, new_slug),
            "note": f"{MARK}: replacement for {task.get('slug')} category={category}",
            "base_branch": task.get("base_branch") or "main",
            "deps": [],
            "material": False,
            "remediation_count": 0,
            "force_coder": _forced_coder(category),
            "model": _forced_coder(category),
            "sensitivity": _sensitivity(task, category),
        }
        if not _insert_task(row):
            skipped += 1
            continue
        _park_original(task, new_slug, category)
        created += 1
        parked += 1
        categories[category] += 1
    summary = {
        "scanned": len(rows),
        "created": created,
        "parked": parked,
        "repaired_original": repaired_original,
        "skipped": skipped,
        "categories": dict(categories),
        "coder": os.environ.get("ORCH_QUARANTINE_CODER") or "ollama",
        "local_only": os.environ.get("ORCH_QUARANTINE_LOCAL_ONLY", "true").lower() in ("1", "true", "yes", "on"),
        "repaired_replacements": repaired,
        "deduped_replacements": deduped,
    }
    try:
        import json
        db.insert("controls", {"key": MARK, "value": json.dumps(summary, default=str),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass
    print(f"{MARK}: {summary}")
    return summary


if __name__ == "__main__":
    print(run())
