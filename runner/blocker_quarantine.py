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
import quarantine_triage

DEFAULT_LIMIT = int(os.environ.get("ORCH_QUARANTINE_LIMIT", "120"))
MAX_BASE_CHARS = int(os.environ.get("ORCH_QUARANTINE_PROMPT_CHARS", "12000"))
MARK = "blocker-quarantine"
REPLACEMENT_CATEGORIES = {"legal", "secret", "security"}

_LEGAL = re.compile(
    r"\blegal review\b|\blegal counsel\b|\bunauthorized practice of law\b|\bupl violation\b|"
    r"\bregulatory (?:blocker|gate|violation|requirement)\b|"
    r"\b(?:requires?|needs?) (?:a )?(?:formal )?(?:legal|compliance) (?:review|opinion|sign-?off|approval)\b|"
    r"\bbroker[- ]dealer registration\b|\bmoney transmission licen[cs]e\b|"
    r"\bsecurities (?:law|registration|violation)\b|"
    r"\bcompliance opinion\b|\bpractice of law\b",
    re.I,
)
# 2026-07-10: beethoven's own subject matter is API token/credential *pool management*
# (module-level singleton acquire()/_pool.acquire() patterns, env vars like
# CRON_SECRET/API_KEY_HASH_SECRET) -- so bare mentions of "token", "credential", "secret",
# or "licensing" in a failure's log/prompt are normal domain vocabulary, not evidence of an
# actual leak. The old bare-keyword regex misclassified ~22% of beethoven's QUARANTINED
# backlog (158/709: "groomed: duplicate queued slug", "agent run failed after 3
# error-retries", etc., none of them actual secret/legal issues) into secret/legal rework,
# burning the constrained local-only coder track and masking the tasks' real failure. Now
# require an actual violation-indicating word (hardcoded/exposed/leaked/committed/etc.) near
# the secret-related term, not just its presence.
_SECRET_VIOLATION_CONTEXT = re.compile(
    r"\b(hardcoded|expos(?:ed|ure|ing)|leak(?:ed|age)?|committed|plaintext|logged|printed|"
    r"detected|checked[- ]in|gitleaks|trufflehog)\b",
    re.I,
)
_SECRET_TERM = re.compile(
    r"\b(secret|api key|token|private key|credential|password)\b|cron_secret|webhook secret",
    re.I,
)
_SECRET_EXPLICIT = re.compile(
    r"hardcoded.*(?:key|secret|token)|\.claude/settings\.local\.json|gitleaks|trufflehog|"
    r"\bleak(?:ed|age)?\b",
    re.I,
)


# 2026-07-11: _SECRET_TERM matches the bare word "token" (routine in any auth-related codebase --
# JWT/CSRF/session tokens) and _SECRET_VIOLATION_CONTEXT matches generic words like "detected" or
# "logged" that appear constantly in linter/build/test output unrelated to any real leak. Checking
# both regexes independently against the WHOLE evidence blob (which can be a long build/test log)
# let them co-occur by pure coincidence -- e.g. a `nuxt build` failure log_tail mentioning an auth
# "token" in one stack frame and a dependency scanner saying "N vulnerabilities detected" in
# another, hundreds of characters apart, with zero relation to each other. Observed in production:
# repeat `nuxt: command not found` build failures on rework-secret-* branches kept getting
# reclassified as "secret" indefinitely. Require the two terms to actually be near each other
# (same sentence/log line, not just the same multi-KB blob) before treating it as a real signal.
_SECRET_PROXIMITY_CHARS = 80


def _is_secret(evidence):
    if _SECRET_EXPLICIT.search(evidence):
        return True
    for term_match in _SECRET_TERM.finditer(evidence):
        start = max(0, term_match.start() - _SECRET_PROXIMITY_CHARS)
        end = min(len(evidence), term_match.end() + _SECRET_PROXIMITY_CHARS)
        if _SECRET_VIOLATION_CONTEXT.search(evidence[start:end]):
            return True
    return False
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


def _evidence_signal(task):
    """Note + log_tail ONLY -- no slug, no prompt. For secret/security specifically, a project's
    or feature's NAME is not evidence of an actual leak. 'santas-secret-workshop' (a real project
    name) or 'rework-secret-<prior-rework>' (this task's own quarantine history) both contain the
    literal word 'secret' with zero relation to whether THIS failure actually exposed one.
    Genuine secret/security blockers are described in the failure note or log
    ("CRON_SECRET exposure in committed config", "gitleaks: hardcoded key detected"), which is
    exactly what this signal keeps.

    One more self-reference path: automated messages (train rebase-conflict notes, branch-missing
    notes) often echo the task's OWN slug/branch name verbatim, e.g. "conflict on
    agent/rework-secret-<slug>". That embeds the word "secret" in the evidence text with zero
    relation to the actual failure (a plain rebase conflict here). Strip the task's own slug out
    of the evidence before scanning so its own name can't self-trigger classification."""
    note = _clean_note_for_classification(task.get("note"))
    log_tail = str(task.get("log_tail") or "")
    slug = str(task.get("slug") or "")
    if slug:
        note = note.replace(slug, "")
        log_tail = log_tail.replace(slug, "")
    return "\n".join((note, log_tail))


def classify(task):
    blocker = _blocker_signal(task)
    evidence = _evidence_signal(task)
    text = blocker + "\n" + str(task.get("prompt") or "")
    state = str(task.get("state") or "").upper()
    # Secret/security classification must come from the blocker EVIDENCE (note/log), never from
    # a slug or prompt that merely contains the word "secret"/"security" as part of an app or
    # feature name. Misclassifying QA failures (or a project's own branding) as secret work
    # sends the wrong directive to the agent and manufactures a self-reinforcing quarantine loop.
    if _is_secret(evidence):
        return "secret"
    if _SECURITY.search(evidence):
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


def classify_multi(task, max_labels=5):
    """Multi-label classifier: identify ALL failure modes in a quarantined task (up to max_labels).

    Unlike classify() which returns a single primary category, this returns a ranked list of
    failure modes with confidence scores, enabling more targeted repair strategies. Each mode
    includes the evidence snippet that triggered it.

    Returns: [{"category": str, "confidence": float, "evidence": str}, ...]
    """
    blocker = _blocker_signal(task)
    evidence = _evidence_signal(task)
    text = blocker + "\n" + str(task.get("prompt") or "")
    state = str(task.get("state") or "").upper()
    results = []

    # Check each classifier independently — a task can have multiple failure modes
    classifiers = [
        ("secret", lambda: _is_secret(evidence), evidence, 0.95),
        ("security", lambda: bool(_SECURITY.search(evidence)), evidence, 0.90),
        ("legal", lambda: bool(_LEGAL.search(text)), text, 0.85),
        ("missing-branch", lambda: bool(_MISSING.search(text)), text, 0.92),
        ("buildfail", lambda: bool(_BUILD.search(text)), text, 0.88),
        ("testfail", lambda: state == "TESTFAIL" or bool(_TEST.search(text)), text, 0.88),
        ("noop", lambda: bool(_NOOP.search(text)), text, 0.90),
        ("oversized", lambda: bool(_EXHAUSTED.search(text)), text, 0.80),
    ]

    for category, check_fn, source, confidence in classifiers:
        try:
            if check_fn():
                # Extract the matching evidence snippet
                snippet = _extract_evidence_snippet(source, category)
                results.append({
                    "category": category,
                    "confidence": confidence,
                    "evidence": snippet[:200],
                })
        except Exception:
            pass

    if not results:
        results.append({
            "category": "rework",
            "confidence": 0.5,
            "evidence": (str(task.get("note") or "") + " " + str(task.get("log_tail") or ""))[:200].strip(),
        })

    # Sort by confidence descending, cap at max_labels
    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results[:max_labels]


def _extract_evidence_snippet(text, category):
    """Extract the relevant snippet from text that triggered a category match."""
    patterns = {
        "secret": _SECRET_TERM,
        "security": _SECURITY,
        "legal": _LEGAL,
        "missing-branch": _MISSING,
        "buildfail": _BUILD,
        "testfail": _TEST,
        "noop": _NOOP,
        "oversized": _EXHAUSTED,
    }
    pat = patterns.get(category)
    if not pat:
        return text[:200]
    m = pat.search(text)
    if not m:
        return text[:200]
    start = max(0, m.start() - 40)
    end = min(len(text), m.end() + 40)
    return text[start:end].strip()


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
    """2026-07-10: ORCH_QUARANTINE_LOCAL_ONLY defaulting true used to short-circuit BEFORE the
    category check below ever ran, forcing crown_jewel (local-only) sensitivity onto EVERY
    quarantine-rework task regardless of category. provider_terms.py treats 'confidential' and
    'crown_jewel' identically (both restrict to local/ollama only), so genuinely sensitive
    categories (secret/security/legal) were already correctly local-only via the category
    branch below -- but non-sensitive categories (buildfail, testfail, missing-branch, noop,
    oversized, generic rework) were ALSO getting force-routed to local-only, and from there into
    local_model_slots' single-heavy-model-at-a-time lock (fcntl.flock, one inference at a time,
    fleet-wide on that machine). With quarantine now producing thousands of replacement tasks
    (beethoven alone: 700+), that single lock became the dominant fleet throughput bottleneck
    (RUNNING stuck at 3-8 despite a 15-slot scheduler ceiling) even while paid-API budget sat at
    0% utilization. Now checks category FIRST: sensitive categories are unconditionally
    confidential/local-only (unchanged behavior), and only non-sensitive categories consult
    ORCH_QUARANTINE_LOCAL_ONLY / the dynamic privacy check, so they CAN use the full concurrent
    coder pool like ordinary tasks do once that env var allows it."""
    if category in ("secret", "security", "legal"):
        return "confidential"
    local_only = os.environ.get("ORCH_QUARANTINE_LOCAL_ONLY", "true").lower() in ("1", "true", "yes", "on")
    if local_only:
        return "crown_jewel"
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
    triage_retried = 0
    for task in rows:
        if MARK in str(task.get("note") or ""):
            skipped += 1
            continue

        # 3-tier triage: give the task a chance to self-recover before quarantining
        try:
            evidence = f"{task.get('note') or ''}\n{task.get('log_tail') or ''}"
            verdict = quarantine_triage.triage(task, evidence)
            if verdict["action"] in ("retry", "restart+retry"):
                rc = int(task.get("remediation_count") or 0)
                db.update("tasks", {"id": task["id"]}, {
                    "state": "QUEUED", "account": None, "updated_at": "now()",
                    "remediation_count": rc + 1,
                    "note": (f"{MARK}: triage tier-{verdict['tier']} {verdict['category']}: "
                             f"{verdict['summary']}")[:500],
                })
                triage_retried += 1
                continue
        except Exception:
            pass  # fail-soft: fall through to normal quarantine path

        category = classify(task)
        # DEPTH CAP: a task whose slug already carries 2+ nested "rework-" segments has already
        # been through this pipeline that many times without landing. Spawning yet another nested
        # replacement is how a single flaky/misclassified task became a 5-deep
        # "rework-legal-rework-legal-rework-legal-..." chain in production, manufacturing
        # QUARANTINED rows forever. Once the cap is hit, stop reworking automatically and put a
        # human in the loop instead.
        if category in REPLACEMENT_CATEGORIES and _rework_depth(task.get("slug")) >= max_depth:
            note = (f"{MARK}: escalated after {max_depth}+ rework attempts (category={category}); "
                    f"needs human review instead of another auto-rework. "
                    f"Last blocker: {(task.get('note') or task.get('log_tail') or '')[:300]}")[:900]
            try:
                db.update("tasks", {"id": task["id"]}, {"state": "BLOCKED", "account": None,
                                                         "updated_at": "now()", "note": note})
                db.insert("approvals", {"project": str(task.get("project_id") or ""), "kind": "quarantine_escalation",
                                        "title": f"{task.get('slug')}: stuck in {category} rework loop, needs a human",
                                        "status": "pending", "detail": note,
                                        "risk": "auto-rework kept respawning without resolving; likely misclassified or a genuine blocker only a human can clear"})
                escalated += 1
            except Exception:
                skipped += 1
            continue
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
        "escalated": escalated,
        "categories": dict(categories),
        "coder": os.environ.get("ORCH_QUARANTINE_CODER") or "ollama",
        "local_only": os.environ.get("ORCH_QUARANTINE_LOCAL_ONLY", "true").lower() in ("1", "true", "yes", "on"),
        "triage_retried": triage_retried,
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
