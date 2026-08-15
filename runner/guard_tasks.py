#!/usr/bin/env python3
"""
guard_tasks.py - the one place a guard bot turns a FINDING into WORK.

Every guard written on 2026-08-02 (stub_guard, crash_loop_detector, clean_clone_gate,
bot_commit_verifier, vercel_config_guard) grew its own copy of "build a slug, check the slug,
insert a task". They then failed in three different ways at once:

  * FLOOD.  stub_guard filed 411 tasks in one sweep (200 of them from scratch worktrees under
    .runtime that do not even exist any more) because it filed one task per SYMBOL with no cap.
  * SILENCE. crash_loop_detector recorded its alert-dedupe state under the traceback signature
    alone while its task slug was job+signature, so firing for ONE job permanently suppressed
    the SAME crash in every other job. 26 of 49 live findings — including 2 of 3 CRITICAL dead
    modules — could never file a task.
  * CHURN.  clean_clone_gate keyed its slug on the TREE sha, so the same unfixed root cause
    (pareto-2080 missing DATABASE_URL et al) filed a brand-new task on every commit.

So: one filer, three guarantees.
  1. DEDUPE is the database, not a local cache file. A slug with an open task is never refiled.
  2. A per-run BUDGET caps how much work one sweep may create (default 12).
  3. SEVERITY routes. "critical" files a high-priority task AND escalates loudly (notify +
     approvals card). "high" files a task. "advisory" is logged and files nothing.

Slugs are stable and collision-proof: the human-readable head is truncated, but a short hash of
the FULL key is appended, so two long symbols that share a 60-char prefix stay distinct.
"""
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

NAME = "guard-tasks"
ENABLED = os.environ.get("ORCH_GUARD_FILE_TASKS", "true").lower() in ("1", "true", "yes", "on")
MAX_PER_RUN = int(os.environ.get("ORCH_GUARD_MAX_TASKS_PER_RUN", "12"))
# Advisory findings are logged, never filed, unless an operator explicitly asks for them.
FILE_ADVISORY = os.environ.get("ORCH_GUARD_FILE_ADVISORY", "false").lower() in ("1", "true", "yes", "on")
SLUG_MAX = 60

# States in which an existing task no longer counts as "already being worked".
TERMINAL = ("DONE", "MERGED", "SHIPPED", "CLOSED", "SHELVED", "CANCELLED")

CRITICAL, HIGH, ADVISORY = "critical", "high", "advisory"
_PRIORITY = {CRITICAL: 95, HIGH: 70, ADVISORY: 30}


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".runtime"))


def log_event(bot, event):
    """Append one structured JSONL record to .runtime/logs/<bot>.log (fail-soft)."""
    row = dict(event)
    row.setdefault("at", time.time())
    row.setdefault("bot", bot)
    try:
        path = os.path.join(_home(), "logs")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, str(bot) + ".log"), "a") as fh:
            fh.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass
    return row


def stable_slug(*parts, **kw):
    """A <=60 char slug that stays UNIQUE for a long key.

    Naive truncation collided in practice: two `stub-tomorrow-fabricated-critical-return-*`
    symbols agreeing on their first 16 characters produced one slug, so the second finding was
    silently swallowed as a duplicate of the first. Append a hash of the full key instead.
    """
    limit = int(kw.get("limit", SLUG_MAX))
    raw = "-".join(str(p) for p in parts if p not in (None, ""))
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-") or "finding"
    if len(slug) <= limit:
        return slug
    digest = hashlib.sha256(slug.encode("utf-8", "replace")).hexdigest()[:6]
    return (slug[:limit - 7].rstrip("-") + "-" + digest)


def open_task(slug):
    """The open (non-terminal) task for <slug>, or None. The DB IS the dedupe store."""
    try:
        rows = db.select("tasks", {"select": "id,state,slug", "slug": "eq.%s" % slug, "limit": "1"}) or []
    except Exception:
        return None
    if rows and (rows[0].get("state") or "").upper() not in TERMINAL:
        return rows[0]
    return None


class Filer:
    """Per-sweep task filer: dedupes on the DB, caps the blast radius, routes by severity.

    Usage:
        filer = guard_tasks.Filer("stub-guard")
        filer.file(project_id, slug, prompt, severity=guard_tasks.CRITICAL, ...)
        summary.update(filer.counters())
    """

    def __init__(self, bot, max_per_run=None, enabled=None):
        self.bot = bot
        self.budget = MAX_PER_RUN if max_per_run is None else int(max_per_run)
        self.enabled = ENABLED if enabled is None else bool(enabled)
        self.filed = 0
        self.duplicate = 0
        self.suppressed = 0      # over budget this run — still ranked, files next sweep
        self.advisory = 0        # logged only, by policy
        self.errors = 0
        self.escalated = 0

    def counters(self):
        return {"tasks_filed": self.filed, "tasks_duplicate": self.duplicate,
                "tasks_over_budget": self.suppressed, "advisory_logged": self.advisory,
                "task_errors": self.errors, "escalated": self.escalated}

    def summary_line(self):
        return ("%d task(s) filed, %d already open, %d deferred (budget %d), "
                "%d advisory logged, %d escalated, %d error(s)"
                % (self.filed, self.duplicate, self.suppressed, self.budget,
                   self.advisory, self.escalated, self.errors))

    def file(self, project_id, slug, prompt, severity=HIGH, kind="build",
             title=None, project_name="", escalate_why=""):
        """File one remediation task. Returns the outcome as a string.

        "filed" | "duplicate" | "over-budget" | "advisory" | "disabled" | "error"
        """
        severity = (severity or HIGH).lower()
        if not self.enabled:
            return "disabled"
        if severity == ADVISORY and not FILE_ADVISORY:
            self.advisory += 1
            log_event(self.bot, {"event": "advisory_finding", "slug": slug, "project": project_name})
            return "advisory"
        if not project_id:
            self.errors += 1
            log_event(self.bot, {"event": "task_error", "slug": slug,
                                 "error": "no project_id — cannot file"})
            return "error"
        if open_task(slug):
            self.duplicate += 1
            return "duplicate"
        if self.filed >= self.budget:
            self.suppressed += 1
            log_event(self.bot, {"event": "task_over_budget", "slug": slug,
                                 "severity": severity, "project": project_name})
            return "over-budget"
        row = {"project_id": project_id, "slug": slug, "state": "QUEUED", "kind": kind,
               "priority": _PRIORITY.get(severity, 70), "prompt": str(prompt)[:12000]}
        try:
            db.insert("tasks", row)
        except Exception as exc:                       # noqa: BLE001 - filing must never abort a sweep
            self.errors += 1
            log_event(self.bot, {"event": "task_error", "slug": slug, "error": str(exc)[:400]})
            return "error"
        self.filed += 1
        log_event(self.bot, {"event": "task_filed", "slug": slug, "severity": severity,
                             "project": project_name})
        if severity == CRITICAL:
            self.escalate(title or slug, escalate_why or str(prompt)[:800], project_name)
        return "filed"

    def escalate(self, headline, why, project_name=""):
        """CRITICAL findings must be LOUD: a notification plus an approvals card.

        This is crash_loop_detector's house pattern, lifted here so every guard escalates the
        same way instead of each inventing its own (or, as three of them did, none at all).
        """
        self.escalated += 1
        text = "%s: %s" % (self.bot, headline)
        try:
            import notify
            notify.send(text[:400])
        except Exception:                              # noqa: BLE001
            pass
        try:
            db.insert("approvals", {
                "project": (project_name or "ORCHESTRATOR")[:80], "kind": "self",
                "status": "pending", "title": text[:200], "why": str(why)[:1000],
                "value": "A guard bot found a defect that produces no error and no red build. "
                         "Silent findings are how preflight stayed 100%% dead for 19 days.",
                "risk": str(why)[:1500],
            })
        except Exception as exc:                       # noqa: BLE001
            log_event(self.bot, {"event": "approval_error", "error": str(exc)[:300]})


def stats():
    """Module statistics for the dashboard."""
    return {"enabled": ENABLED, "max_tasks_per_run": MAX_PER_RUN,
            "file_advisory": FILE_ADVISORY}


if __name__ == "__main__":
    print(json.dumps(stats(), indent=2))
