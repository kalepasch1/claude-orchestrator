"""A task must not reach a success state with no evidence.

The 2026-08-04 audit moved 10,598 tasks out of MERGED into PHANTOM_UNVERIFIED
because their success state was manufactured rather than evidenced. The merge
path was then fixed to require an artifact_commit and it worked -- 218/218 and
169/169 merges on 08-05 / 08-06 carry real commits. The same requirement was
never applied to the NON-merge terminal states, so a report-only task can still
land in DONE with an empty log_tail, an untouched note, and no row in
task_artifacts / runs / outcomes. Such a task is indistinguishable from one that
did the work perfectly and one that did nothing at all.

This module closes that gap for FUTURE transitions only. It never
bulk-reclassifies history -- that is a separate, operator-authorised decision.

Fail-soft is the governing rule: an over-eager guard that blocks real work is
worse than the gap it closes, so any unexpected exception lets the transition
through untouched.
"""
import os

import db

# Non-MERGED success states that must carry evidence. MERGED is already gated by
# the merge path's artifact_commit requirement.
GUARDED_STATES = {"DONE"}

# Reuse the existing state rather than inventing a new one, so the phantom
# tooling (phantom_reclassify, phantom_recovery, bottleneck_detector) already
# understands these rows.
FALLBACK_STATE = "PHANTOM_UNVERIFIED"

ALARM_GATE = "done_evidence"
ALARM_KIND = "evidence_missing"

# Task kinds whose entire deliverable is written findings rather than a diff.
# For these the agent's final message IS the artifact, so it gets persisted into
# log_tail and satisfies the requirement the obvious way.
REPORT_KINDS = {
    "toolchain-repair", "toolchain-diagnose", "recovery", "diagnose",
    "diagnosis", "report", "analysis", "audit", "investigation",
}

LOG_TAIL_LIMIT = int(os.environ.get("ORCH_EVIDENCE_LOG_TAIL_CHARS", "16000"))

ENABLED = os.environ.get("ORCH_DONE_EVIDENCE_GATE", "1").strip().lower() not in {
    "0", "false", "off", "no",
}


def _text(value):
    return (value if isinstance(value, str) else "" if value is None else str(value)).strip()


def _task_row(task_id, row=None):
    if isinstance(row, dict) and row:
        return row
    rows = db.select("tasks", {"id": f"eq.{task_id}", "limit": "1"}) or []
    return rows[0] if rows else {}


def is_report_task(task):
    """True when the task's deliverable is a written report, not a diff."""
    kind = _text((task or {}).get("kind")).lower()
    if kind in REPORT_KINDS:
        return True
    slug = _text((task or {}).get("slug")).lower()
    return any(marker in slug for marker in ("diagnose", "audit", "report-only", "investigate"))


def capture_report_log(task_id, output, task=None, limit=LOG_TAIL_LIMIT):
    """Persist an agent's final output into log_tail so a report task can be evidenced.

    Only fills an EMPTY log_tail -- never overwrites a real captured log. Returns
    the text that was written, or None when nothing was written.
    """
    try:
        text = _text(output)
        if not text:
            return None
        task = _task_row(task_id, task)
        if _text(task.get("log_tail")):
            return None
        trimmed = text[-limit:] if len(text) > limit else text
        db.update("tasks", {"id": task_id}, {"log_tail": trimmed, "updated_at": "now()"})
        if isinstance(task, dict):
            task["log_tail"] = trimmed
        return trimmed
    except Exception:
        return None


def collect_evidence(task_id, task=None, pending=None):
    """Return (found, missing) -- the evidence that exists for this task.

    `pending` is the kwargs dict of the in-flight transition, so evidence being
    written by the very same call (e.g. set_state(..., log_tail=...)) counts.
    """
    found, missing = [], []
    task = _task_row(task_id, task)
    pending = pending if isinstance(pending, dict) else {}

    def _field(name):
        return _text(pending.get(name)) or _text(task.get(name))

    if _field("log_tail"):
        found.append("log_tail")
    else:
        missing.append("log_tail")

    commit = _field("artifact_commit") or _field("artifact_ref")
    if commit:
        found.append("artifact_commit")
    else:
        missing.append("artifact_commit")

    slug = _text(task.get("slug"))
    if slug:
        rows = db.select("task_artifacts",
                         {"select": "slug", "slug": f"eq.{slug}", "limit": "1"}) or []
        if rows:
            found.append("task_artifacts")
        else:
            missing.append("task_artifacts")
    else:
        missing.append("task_artifacts")

    rows = db.select("outcomes",
                     {"select": "id", "task_id": f"eq.{task_id}", "limit": "1"}) or []
    if rows:
        found.append("outcomes")
    else:
        missing.append("outcomes")

    return found, missing


def _alarm_open(task_id):
    rows = db.select("orch_gate_alarms", {
        "select": "id", "gate": f"eq.{ALARM_GATE}", "kind": f"eq.{ALARM_KIND}",
        "verdict": f"eq.{task_id}", "resolved_at": "is.null", "limit": "1"}) or []
    return bool(rows)


def raise_alarm(task_id, task, missing):
    """Open one orch_gate_alarms row per refused task. Deduped, never spammed."""
    try:
        if _alarm_open(task_id):
            return False
        slug = _text((task or {}).get("slug")) or str(task_id)
        detail = (f"task '{slug}' tried to reach DONE with no evidence "
                  f"(missing: {', '.join(missing) or 'everything'}); "
                  f"held as {FALLBACK_STATE}")
        db.insert("orch_gate_alarms", {
            "gate": ALARM_GATE, "kind": ALARM_KIND, "verdict": str(task_id),
            "n": len(missing), "detail": detail[:500]})
        print(f"[done_evidence_gate] ALARM: {detail}", flush=True)
        return True
    except Exception:
        return False


def check(task_id, task=None, pending=None):
    """Evidence verdict for a task. Never raises."""
    try:
        found, missing = collect_evidence(task_id, task=task, pending=pending)
        return {"ok": bool(found), "found": found, "missing": missing, "error": None}
    except Exception as exc:                                  # fail-soft
        return {"ok": True, "found": [], "missing": [], "error": str(exc)}


def guard(task_id, kw, task=None):
    """Gate a set_state() transition. Returns the kwargs to actually apply.

    A guarded success state with zero evidence is rewritten to
    PHANTOM_UNVERIFIED with a note naming what was missing, so the gap is
    visible instead of silent. Everything else passes through untouched.
    """
    try:
        if not ENABLED:
            return kw
        if not isinstance(kw, dict) or kw.get("state") not in GUARDED_STATES:
            return kw

        task = _task_row(task_id, task)

        # A report-only task's deliverable is its written output. If the caller
        # handed us one on this very transition, that IS the artifact.
        if is_report_task(task) and _text(kw.get("log_tail")):
            capture_report_log(task_id, kw.get("log_tail"), task=task)

        verdict = check(task_id, task=task, pending=kw)
        if verdict["ok"] or verdict["error"]:
            return kw

        missing = verdict["missing"]
        raise_alarm(task_id, task, missing)
        held = dict(kw)
        held["state"] = FALLBACK_STATE
        reason = (f"done_evidence_gate: refused DONE with no evidence "
                  f"(missing: {', '.join(missing) or 'everything'})")
        prior = _text(kw.get("note"))
        held["note"] = f"{reason} | {prior}"[:2000] if prior else reason
        return held
    except Exception:                                          # fail-soft
        return kw
