"""
prompt_integrity.py — one place that decides whether a task prompt is real.

THE TWO QUARANTINE CAUSES THIS CLOSES (measured over 7 days)
    "GC: preflight: PATCH TEMPLATE or garbage prompt"   28 tasks
    "spec-lost: prompt overwritten with the stub"       87 tasks

    Different symptoms, one shape: a prompt that cannot be worked lands in the queue and
    is only caught at PREFLIGHT — after the task exists, has consumed a slot, and has
    burned an attempt. Both are cheap to refuse at the write boundary and expensive to
    clean up afterwards.

WHY THE EXISTING GUARDS MISS THEM
    db.insert has a prompt gate, but:
      (1) it tests `prompt.startswith("PATCH TEMPLATE")`, so a stub carrying any preamble
          (a MERGED-DIFF LIBRARY block, an ORCHESTRATION PIPELINE CONTRACT header) sails
          through — and those preambles are exactly what the task-filing paths prepend.
          preflight_filter already knows how to strip them; the insert gate does not.
      (2) it runs on INSERT only. "spec-lost" is an UPDATE: a real specification is
          replaced in place by "Complete the task '<slug>'.". db.update never looked at
          prompts at all, so the destructive write was invisible to every gate until the
          gutted task reached preflight and was quarantined.

    agentic_repair already defends its own path by omitting `prompt` when the caller did
    not select it. That fixes one writer. This fixes the boundary, so the next writer
    cannot reintroduce it.

THE RULE FOR UPDATES
    Refusing all stub writes is wrong — a task may legitimately be created with a thin
    prompt and later refined. What must never happen is REPLACING a real specification
    with a stub. So an update is judged as a transition: stub-over-substance is refused,
    everything else is allowed. That needs the current prompt, which the caller supplies;
    when it cannot be determined the write is ALLOWED (fail-open), because a guard that
    blocks legitimate writes on missing information does more damage than the bug.

Everything here is pure and side-effect free so it can be tested without a database.
"""
import os
import re

__all__ = ["is_stub", "garbage_reason", "reject_reason_for_insert",
           "reject_reason_for_update", "strip_preamble", "STUB_RE"]

# "Complete the task 'some-slug'." — the exact stub that overwrites real specs.
STUB_RE = re.compile(r"^\s*Complete the task '[^']*'\.?\s*$", re.I)

# Mirrors preflight_filter._GARBAGE_PROMPT_RE so the two gates agree. If they disagree,
# a task is accepted at the door and quarantined later, which is the bug being fixed.
GARBAGE_RE = re.compile(r"PATCH TEMPLATE [0-9a-f]|patch-template-corrupt|^[\s#\-\*]*$", re.I)

PREAMBLE_MARKERS = ("## ORCHESTRATION PIPELINE CONTRACT", "## TASK", "## OBJECTIVE")

MIN_PROMPT_CHARS = int(os.environ.get("ORCH_PROMPT_MIN_CHARS", "20"))
# A genuine stub has the marker near the top of a SHORT body. The same marker deep inside
# a long real prompt is evidence of reuse (a quoted prior diff), not garbage — matching on
# those cost 10 real 5KB work prompts on 2026-07-31, per preflight_filter's own comment.
GARBAGE_HEAD_CHARS = int(os.environ.get("ORCH_PROMPT_GARBAGE_HEAD", "120"))
GARBAGE_SHORT_BODY = int(os.environ.get("ORCH_PROMPT_GARBAGE_SHORT_BODY", "500"))

_ERROR_PREFIXES = ("Error", "error:", "Traceback", "fatal:")


def strip_preamble(prompt):
    """Drop injected library/contract preambles so the real body is judged, not the wrapper."""
    text = str(prompt or "")
    for marker in PREAMBLE_MARKERS:
        idx = text.find(marker)
        if idx >= 0:
            return text[idx:]
    if text.startswith("MERGED-DIFF LIBRARY"):
        eol = text.find("\n\n")
        if eol > 0:
            return text[eol + 2:]
    return text


def is_stub(prompt):
    """True for the 'Complete the task <slug>.' placeholder — content-free by construction."""
    return bool(STUB_RE.match(str(prompt or "")))


def garbage_reason(prompt):
    """Why this prompt is unworkable, or None. Same judgement preflight applies."""
    raw = str(prompt or "").strip()
    if not raw or len(raw) < MIN_PROMPT_CHARS:
        return "empty or trivial prompt"
    if is_stub(raw):
        return "unfilled 'Complete the task' stub"
    body = strip_preamble(raw)
    match = GARBAGE_RE.search(body)
    if match and (match.start() < GARBAGE_HEAD_CHARS
                  or len(body.strip()) < GARBAGE_SHORT_BODY):
        return "unfilled PATCH TEMPLATE / garbage prompt"
    lines = [ln for ln in raw.split("\n")[:5] if ln.strip()]
    if lines and all(ln.startswith(_ERROR_PREFIXES) for ln in lines):
        return "prompt is only error messages"
    return None


def reject_reason_for_insert(prompt):
    """Why this task must not be created, or None."""
    return garbage_reason(prompt)


def reject_reason_for_update(new_prompt, current_prompt):
    """Why this prompt WRITE must be refused, or None.

    Judged as a transition, not as a value: replacing a real specification with a stub is
    destructive and irreversible, while writing a stub over nothing is merely unhelpful.
    Fail-open when the current prompt is unknown — a guard that blocks legitimate writes
    on missing information causes more damage than the bug it prevents.
    """
    if new_prompt is None:
        return None                        # not touching the prompt at all
    current = str(current_prompt or "").strip()
    if not current:
        return None                        # nothing to destroy, and nothing to compare
    if garbage_reason(current) is not None:
        return None                        # current is already unusable; let it be replaced
    reason = garbage_reason(new_prompt)
    if reason is None:
        return None                        # substance replacing substance: fine
    return (f"refusing to overwrite a {len(current)}-char specification with "
            f"a {reason}")
