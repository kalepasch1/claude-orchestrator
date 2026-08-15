#!/usr/bin/env python3
"""
preflight_gate.py - cost/value control before expensive agentic work.

It never terminally blocks work. If a cheap model thinks a task is vague/no-diff, the task
is rewritten into an explicit implementation directive and left QUEUED so the fleet keeps
moving instead of surfacing "blocked_task" interruptions.

Enhanced with scope definition and ambiguity flagging to reduce unnecessary remediation
and improve routing efficiency per operator feedback.
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract
try:
    import app_triage
except Exception:
    app_triage = None

BATCH = int(os.environ.get("PREFLIGHT_BATCH", "15"))
PROTECT = ("canary-", "sec-rls-", "fix-", "verify-", "rollback-", "rls-", "auto-approve", "deploy")


def _protected(slug):
    s = (slug or "").lower()
    return any(s.startswith(p) or p in s for p in PROTECT)


# --- triage response parsing -------------------------------------------------
# The triage prompt asks for a three-part answer ("1. First line: YES or NO",
# "2. SCOPE DEFINITION:", "3. AMBIGUITIES/CONCERNS:"), so the parser has to
# accept the numbered/markdown shapes the prompt itself invites. The original
# parser only matched a bare "YES" on line 0, so "1. YES" and "**YES**" both
# fell through to actionable=False with an empty scope. That mis-parse ran for
# 18 days and tagged 1,436 / 1,480 tasks (97.0%) "Preflight scope concern: Not
# clearly defined". See check_liveness() for the alarm that now catches this
# class of silent gate failure.

_EMPHASIS_RE = re.compile(r"[*_`~]+")
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-–—*•>+]\s*|#{1,6}\s*|\(?\d+\s*[.)]\s*)+")
_LABEL_PREFIX_RE = re.compile(
    r"^(?:first\s+line|answer|verdict|decision|actionable|response)\s*[:\-–—]\s*",
    re.IGNORECASE)
_VERDICT_RE = re.compile(r"^(YES|NO)\b[\s:;,.\-–—]*(.*)$", re.IGNORECASE)
_SCOPE_RE = re.compile(r"^SCOPE(?:\s+DEFINITION)?\s*[:\-–—]\s*(.*)$", re.IGNORECASE)
_AMBIG_RE = re.compile(
    r"^(?:AMBIGUITIES(?:\s*/\s*CONCERNS)?|CONCERNS(?:\s*/\s*AMBIGUITIES)?"
    r"|AMBIGUITY|RISKS?)\s*[:\-–—]\s*(.*)$", re.IGNORECASE)
_OTHER_HEADER_RE = re.compile(r"^[A-Z][A-Z0-9 /_&-]{2,40}\s*[:\-–—]")
_PLACEHOLDER_RE = re.compile(
    r"^(?:none|n/?a|nil|null|not\s+applicable|none\s+(?:identified|found|noted)"
    r"|no\s+(?:ambiguities|concerns|issues)[\w\s]*)[.!]?$", re.IGNORECASE)

# The verdict must sit near the top; scanning the whole body would let a stray
# "No changes needed" deep in the prose flip an otherwise actionable task.
_VERDICT_SCAN_LINES = 6


def _denoise(line: str) -> str:
    """Strip markdown emphasis, list/heading markers and surrounding whitespace."""
    s = _EMPHASIS_RE.sub("", line or "").strip()
    return _LIST_PREFIX_RE.sub("", s).strip()


def _extract_scope_and_ambiguities(response_text: str) -> tuple:
    """Extract scope definition and ambiguities from a triage response.

    Pure function (no side effects) so it can be table-tested. Tolerates every
    shape the triage prompt invites: bare "YES", "1. YES", "**YES**", leading
    whitespace, "YES:", "YES - ...", "Answer: NO", lowercase, and section
    headers with or without numbering/emphasis. Returns actionable=False only
    for a genuine NO or an empty/unparseable response.

    Returns (actionable: bool, scope_def: str, ambiguities: list[str])
    """
    text = (response_text or "").strip()
    if not text:
        return False, "", []

    raw_lines = text.split("\n")
    actionable = False
    verdict_idx = -1
    verdict_tail = ""

    scanned = 0
    for i, raw in enumerate(raw_lines):
        cleaned = _denoise(raw)
        if not cleaned:
            continue
        if _SCOPE_RE.match(cleaned) or _AMBIG_RE.match(cleaned):
            break  # sections have started; there is no verdict line to find
        m = _VERDICT_RE.match(_LABEL_PREFIX_RE.sub("", cleaned).strip())
        if m:
            actionable = m.group(1).upper() == "YES"
            verdict_tail = (m.group(2) or "").strip()
            verdict_idx = i
            break
        scanned += 1
        if scanned >= _VERDICT_SCAN_LINES:
            break

    scope_lines, ambiguity_lines = [], []
    section = None
    for i, raw in enumerate(raw_lines):
        if i == verdict_idx:
            continue
        cleaned = _denoise(raw)
        if not cleaned:
            continue
        m = _SCOPE_RE.match(cleaned)
        if m:
            section = "scope"
            rest = m.group(1).strip()
            if rest:
                scope_lines.append(rest)
            continue
        m = _AMBIG_RE.match(cleaned)
        if m:
            section = "ambiguities"
            rest = m.group(1).strip()
            if rest and not _PLACEHOLDER_RE.match(rest):
                ambiguity_lines.append(rest)
            continue
        if _OTHER_HEADER_RE.match(cleaned):
            section = None  # an unrelated ALL-CAPS heading closes the section
            continue
        if section == "scope":
            scope_lines.append(cleaned)
        elif section == "ambiguities" and not _PLACEHOLDER_RE.match(cleaned):
            ambiguity_lines.append(cleaned)

    scope_def = " ".join(s for s in scope_lines if s).strip()
    if not scope_def and verdict_tail and not _PLACEHOLDER_RE.match(verdict_tail):
        scope_def = verdict_tail  # "YES - add retry to fetch.ts"

    return actionable, scope_def, [a for a in ambiguity_lines if a]


# --- liveness assertion ------------------------------------------------------
# A gate that answers the same way for essentially every input is not gating.
# The broken parser above returned False for 97.0% of 1,480 tasks and nobody
# noticed for 18 days, because "everything is non-actionable" looks exactly like
# "the fleet queued a lot of vague tasks". This watches the verdict distribution
# over a rolling window and alarms when the gate stops discriminating.

LIVENESS_WINDOW = int(os.environ.get("PREFLIGHT_LIVENESS_WINDOW", "200"))
LIVENESS_THRESHOLD = float(os.environ.get("PREFLIGHT_LIVENESS_THRESHOLD", "0.95"))
LIVENESS_MIN_SAMPLES = int(os.environ.get("PREFLIGHT_LIVENESS_MIN_SAMPLES", "50"))
_LIVENESS_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".runtime", "preflight_verdicts.json")


def check_liveness(window, threshold=None, min_samples=None) -> tuple:
    """Pure predicate: does this verdict window show a gate that stopped gating?

    `window` is a sequence of bools (True = actionable). Returns
    (alarm: bool, detail: str). Alarms when either verdict exceeds `threshold`
    of a window of at least `min_samples` — deliberately symmetric, since an
    all-YES gate is exactly as useless as the all-NO one we shipped.
    """
    threshold = LIVENESS_THRESHOLD if threshold is None else threshold
    min_samples = LIVENESS_MIN_SAMPLES if min_samples is None else min_samples
    n = len(window)
    if n < min_samples:
        return False, f"preflight liveness: {n}/{min_samples} samples, not yet evaluable"
    yes = sum(1 for v in window if v)
    majority = max(yes, n - yes)
    share = majority / float(n)
    verdict = "YES" if yes >= n - yes else "NO"
    detail = (f"preflight gate returned {verdict} for {share:.1%} of the last {n} "
              f"triaged tasks (alarm above {threshold:.0%}) — the gate is not "
              f"discriminating; suspect a parser or triage-prompt regression")
    if share <= threshold:
        detail = (f"preflight liveness OK: majority verdict {verdict} at {share:.1%} "
                  f"of {n} samples (alarm above {threshold:.0%})")
        return False, detail
    return True, detail


def _load_window() -> list:
    try:
        with open(_LIVENESS_STATE) as f:
            return [bool(v) for v in (json.load(f) or {}).get("verdicts", [])][-LIVENESS_WINDOW:]
    except Exception:
        return []


def _save_window(window) -> None:
    try:
        os.makedirs(os.path.dirname(_LIVENESS_STATE), exist_ok=True)
        tmp = _LIVENESS_STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"verdicts": list(window)[-LIVENESS_WINDOW:]}, f)
        os.replace(tmp, _LIVENESS_STATE)
    except Exception as e:
        print(f"preflight: could not persist liveness window: {e}")


def record_verdicts(verdicts) -> tuple:
    """Fold this cycle's verdicts into the rolling window and alarm if flat."""
    window = (_load_window() + [bool(v) for v in verdicts])[-LIVENESS_WINDOW:]
    _save_window(window)
    alarm, detail = check_liveness(window)
    if alarm:
        print(f"preflight LIVENESS ALARM: {detail}")
        try:
            import error_alerter
            error_alerter.alert("preflight_gate_not_discriminating",
                                project_id="orchestrator", detail=detail,
                                severity="high")
        except Exception as e:
            print(f"preflight: liveness alarm dispatch failed: {e}")
    return alarm, detail


def run():
    if not app_triage:
        print("preflight: app_triage unavailable; skipping"); return
    rows = db.select("tasks", {"select": "id,slug,prompt,kind,material,note,model,force_coder,project_id", "state": "eq.QUEUED",
                              # Updating a row moves it to the back, so every queued
                              # task is eventually triaged instead of screening the
                              # same oldest BATCH forever.
                              "order": "updated_at.asc", "limit": str(BATCH)}) or []
    try:
        projects = {p["id"]: p.get("name", "") for p in
                    (db.select("projects", {"select": "id,name"}) or [])}
    except Exception:
        projects = {}
    sharpened = 0
    verdicts = []
    for t in rows:
        if _protected(t.get("slug", "")):
            continue
        prompt = pipeline_contract.original_request(t.get("prompt") or "")[:1500]
        ask = ("You are a build-task triager. Analyze this task and respond with:\n\n"
               "1. First line: YES or NO (will this produce an actual committable code/file change?)\n"
               "2. SCOPE DEFINITION: What specific changes will be made, to which files/components?\n"
               "3. AMBIGUITIES/CONCERNS: List any vagueness, missing context, or potential issues.\n\n"
               "Vague, duplicate, already-done, discussion-only, or under-specified tasks => NO.\n\n"
               "TASK:\n" + prompt)
        try:
            r = app_triage.run("orchestrator", "preflight_triage", ask, task_class="rating")
            response_text = (r or {}).get("text", "").strip()
        except Exception as e:
            print(f"preflight {t['slug']}: {e}"); continue

        actionable, scope_def, ambiguities = _extract_scope_and_ambiguities(response_text)
        verdicts.append(actionable)
        existing_note = t.get("note") or ""

        if not actionable:
            revised = ((t.get("prompt") or "").rstrip() +
                       "\n\nPREFLIGHT DIRECTIVE\n"
                       "A cheap preflight model thought this might not produce a concrete diff. "
                       "Do not stop at analysis. Implement the smallest useful code/file change, "
                       "or convert the idea into a specific test/docs/config improvement and commit it.\n"
                       f"Preflight scope concern: {scope_def[:220] if scope_def else 'Not clearly defined'}")
            # NOTE (2026-08-02): must NOT start with "preflight:" — preflight_filter's
            # skip regex (r"preflight:|GC:") treats that prefix as a kill marker, so this
            # SUCCESS path was making every sharpened task permanently unclaimable
            # (73 tasks sat QUEUED-but-never-claimed before this was caught).
            existing_note = "preflight-ok: sharpened instead of blocked"
            sharpened += 1
        else:
            revised = t.get("prompt") or ""

        scope_note = ""
        if scope_def:
            scope_note = f"scope: {scope_def[:200]}"
        if ambiguities:
            ambiguity_note = f"ambiguities: {'; '.join(ambiguities[:3])}"
            scope_note = f"{scope_note}; {ambiguity_note}" if scope_note else ambiguity_note

        if scope_note:
            existing_note = f"{existing_note}; {scope_note}" if existing_note else scope_note

        explicit_route = any(mark in existing_note.lower() for mark in
                             ("agentic-repair", "forced coder", "coder-canary"))
        admission = pipeline_contract.task_fields(
            pipeline_contract.original_request(revised),
            project=projects.get(t.get("project_id"), "orchestrator"),
            kind=t.get("kind") or "build", source="preflight-gate",
            slug=t.get("slug") or "", material=bool(t.get("material")),
            existing_note=existing_note,
            model=t.get("model") if explicit_route else None,
            force_coder=t.get("force_coder") if explicit_route else None,
        )
        db.update("tasks", {"id": t["id"]}, {
            **admission, "updated_at": "now()",
        })
    alarm, liveness_detail = record_verdicts(verdicts)
    print(f"preflight: screened {len(rows)} queued, sharpened {sharpened} non-actionable predictions")
    print(f"preflight: {liveness_detail}")
    return {"screened": len(rows), "sharpened": sharpened, "liveness_alarm": alarm}


if __name__ == "__main__":
    run()
