#!/usr/bin/env python3
"""
remediation_bots.py — autonomous remediation WITH the circuit breakers the
existing self-healer lacks.

READ THIS BEFORE CHANGING ANYTHING HERE.

This system already had autonomous remediation, and it caused an outage.
`_self_heal_qa` in release_train.py reacts to a red gate by queueing a fix
task. The planner decomposes that into a DAG of 30-40 sub-tasks. Something in
the DAG is always RUNNING, which renewed the release hold forever, so the
release train stopped attempting and never retried. Verified deploys went from
151 in the week of 2026-07-20 to 0 for the next 17 days, and nobody noticed,
because a permanently held train looks exactly like an idle one.

So this module is not "more bots". Every property below exists because that
loop lacked it:

1. BOUNDED ATTEMPTS   — max MAX_ATTEMPTS_24H per (remediator, problem_key,
                        subject) per 24h. Attempt N+1 opens an operator card
                        instead. The counter is DERIVED from remediation_log,
                        so a process restart cannot reset it.
2. CIRCUIT BREAKER    — BREAKER_THRESHOLD consecutive failures for a
                        problem_key disables that remediator for that key until
                        an operator clears it. The trip is written to
                        orch_gate_alarms.
3. NO SELF-BLOCKING   — a remediator declares `creates_queue_work`. Any
                        remediator that could hold the gate it is trying to
                        unblock is refused at registration. See
                        `assert_cannot_self_block`.
4. VISIBLE BY DEFAULT — every action, skip and no-op writes a row, and every
                        cycle emits a heartbeat whether or not it acted.
5. EVIDENCE OR IT DIDN'T HAPPEN — success requires the signal to be RE-MEASURED
                        after the action and found clear. Dispatching is not
                        success.

ROLLOUT: every remediator ships OFF. `ORCH_REMEDIATOR_<NAME>` accepts
"off" (default), "observe" (log what it WOULD do, write nothing) or "on".
Nothing here enables itself.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MAX_ATTEMPTS_24H = int(os.environ.get("ORCH_REMEDIATION_MAX_ATTEMPTS", "3") or 3)
BREAKER_THRESHOLD = int(os.environ.get("ORCH_REMEDIATION_BREAKER_N", "3") or 3)
ATTEMPT_WINDOW_S = 24 * 3600
#: STRANDED_BRANCH requeues one task at a time; this caps a single run so a
#: bad detector cannot turn into a bulk sweep.
MAX_REQUEUE_PER_RUN = int(os.environ.get("ORCH_REMEDIATION_MAX_REQUEUE", "25") or 25)

MODE_OFF = "off"
MODE_OBSERVE = "observe"
MODE_ON = "on"
_VALID_MODES = (MODE_OFF, MODE_OBSERVE, MODE_ON)

OUTCOME_ACTED = "acted"
OUTCOME_OBSERVED = "observed"
OUTCOME_SKIPPED = "skipped"
OUTCOME_TRIPPED = "tripped"
OUTCOME_ESCALATED = "escalated"
OUTCOME_HEARTBEAT = "heartbeat"
OUTCOME_FAILED = "failed"

#: Outcomes that count against the circuit breaker. A skip is not a failure —
#: a breaker that trips on skips would disable an idle remediator.
_FAILURE_OUTCOMES = frozenset({OUTCOME_FAILED})
#: Outcomes that consume an attempt.
_ATTEMPT_OUTCOMES = frozenset({OUTCOME_ACTED, OUTCOME_FAILED})


def mode_for(name):
    """Read ORCH_REMEDIATOR_<NAME>. Anything unrecognised is OFF, on purpose."""
    raw = (os.environ.get(f"ORCH_REMEDIATOR_{name.upper()}", "") or "").strip().lower()
    if raw in ("1", "true", "yes", "enabled", MODE_ON):
        return MODE_ON
    if raw in (MODE_OBSERVE, "dry-run", "dryrun", "shadow"):
        return MODE_OBSERVE
    return MODE_OFF


# ── storage ──────────────────────────────────────────────────────────────────

class Store:
    """Everything that touches the outside world, in one injectable place.

    Tests substitute a FakeStore; nothing else in this module imports db, so
    "observe mode performs no writes" is a property that can actually be
    asserted rather than hoped for.
    """

    def __init__(self, db_module=None):
        if db_module is None:
            import db as db_module  # deferred: import cost and test isolation
        self._db = db_module

    # -- log --
    def append_log(self, row):
        self._db.insert("remediation_log", row)

    def recent_log(self, remediator, problem_key, subject, since_epoch):
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(since_epoch))
        return self._db.select("remediation_log", {
            "select": "ts,remediator,problem_key,subject,outcome,attempt_n",
            "remediator": f"eq.{remediator}",
            "problem_key": f"eq.{problem_key}",
            "subject": f"eq.{subject}",
            "ts": f"gte.{since}",
            "order": "ts.desc",
            "limit": "50",
        }) or []

    # -- alarms --
    def raise_alarm(self, gate, kind, detail):
        self._db.insert("orch_gate_alarms", {
            "gate": gate, "kind": kind, "verdict": "trip", "detail": detail,
        })

    # -- generic --
    def select(self, table, params):
        return self._db.select(table, params) or []

    def update(self, table, match, patch):
        return self._db.update(table, match, patch)


class ObserveStore:
    """Wraps a Store and lets ONLY remediation_log and alarm writes through.

    Observe mode must be provably read-only with respect to tasks/controls, so
    the block lives here rather than in each remediator's act().
    """

    WRITABLE = frozenset({"remediation_log"})

    def __init__(self, inner):
        self._inner = inner
        self.blocked_writes = []

    def append_log(self, row):
        self._inner.append_log(row)

    def recent_log(self, *a, **kw):
        return self._inner.recent_log(*a, **kw)

    def raise_alarm(self, *a, **kw):
        # An alarm is a notification, not a state change: it is the one thing
        # observe mode is allowed to do, otherwise a trip would be invisible.
        self._inner.raise_alarm(*a, **kw)

    def select(self, table, params):
        return self._inner.select(table, params)

    def update(self, table, match, patch):
        self.blocked_writes.append((table, match, patch))
        return None


# ── the base remediator ──────────────────────────────────────────────────────

class SelfBlockingRemediator(Exception):
    """Raised when a remediator could hold the gate it is meant to clear."""


class Remediator:
    """One bounded, breakered, evidence-gated remediation loop.

    Subclasses implement:
      detect()          -> [{"subject": str, "evidence": {...}}, ...]
      act(finding)      -> str describing what was done
      measure(subject)  -> evidence dict, re-read from source
      cleared(before, after) -> bool
    """

    name = "base"
    problem_key = "base"
    #: True if acting can create QUEUED work. A remediator that both creates
    #: queue work and guards a gate that queue work holds is the deadlock.
    creates_queue_work = False
    #: The gate this remediator is trying to unblock, if any.
    guards_gate = None

    def __init__(self, store, mode=None, now=None):
        self.store = store
        self.mode = mode if mode in _VALID_MODES else mode_for(self.name)
        self._now = now or time.time
        assert_cannot_self_block(self)

    # -- bounds ---------------------------------------------------------------

    def _history(self, subject):
        since = self._now() - ATTEMPT_WINDOW_S
        try:
            return self.store.recent_log(self.name, self.problem_key, subject, since)
        except Exception:
            # Fail-soft on a log read, but fail CLOSED on the bound: with no
            # history we cannot prove we are under the cap, so we do not act.
            return None

    def attempts_used(self, subject):
        rows = self._history(subject)
        if rows is None:
            return MAX_ATTEMPTS_24H  # unknown history == treat as exhausted
        return sum(1 for r in rows if r.get("outcome") in _ATTEMPT_OUTCOMES)

    def breaker_tripped(self, subject):
        """N consecutive failures (most recent first) trips the breaker.

        Stays tripped: a success is the only thing that resets the streak, and
        once tripped we never act, so no success can be recorded without an
        operator clearing the log/flag first.
        """
        rows = self._history(subject)
        if rows is None:
            return True
        streak = 0
        for r in rows:
            outcome = r.get("outcome")
            if outcome in _FAILURE_OUTCOMES:
                streak += 1
                if streak >= BREAKER_THRESHOLD:
                    return True
            elif outcome in _ATTEMPT_OUTCOMES:
                return False  # a success ends the streak
        return False

    # -- logging --------------------------------------------------------------

    def _log(self, outcome, subject="", action="", attempt_n=0,
             before=None, after=None, detail=""):
        row = {
            "remediator": self.name,
            "problem_key": self.problem_key,
            "subject": subject or "",
            "action": action or "",
            "attempt_n": int(attempt_n or 0),
            "outcome": outcome,
            "evidence_before": before,
            "evidence_after": after,
            "mode": self.mode,
            "detail": (detail or "")[:2000],
        }
        try:
            self.store.append_log(row)
        except Exception:
            pass  # fail-soft: a log outage must not stop the cycle
        return row

    # -- the cycle ------------------------------------------------------------

    def run_cycle(self):
        """One pass. ALWAYS writes a heartbeat, acted or not.

        Returns the list of rows written, which is what the tests assert on.
        """
        rows = []
        if self.mode == MODE_OFF:
            rows.append(self._log(OUTCOME_HEARTBEAT, detail="mode=off"))
            return rows

        try:
            findings = self.detect() or []
        except Exception as exc:
            rows.append(self._log(OUTCOME_FAILED, action="detect",
                                  detail=f"detect raised: {exc}"))
            rows.append(self._log(OUTCOME_HEARTBEAT, detail="detect failed"))
            return rows

        # One subject is handled at most once per cycle. Two detectors (or one
        # detector run over two states) surfacing the same subject must not burn
        # two of its three attempts in a single pass.
        handled = set()
        for finding in findings:
            subject = str(finding.get("subject", ""))
            if subject in handled:
                continue
            handled.add(subject)
            rows.append(self._handle(finding))

        rows.append(self._log(
            OUTCOME_HEARTBEAT,
            detail=(f"cycle complete: {len(handled)} subject(s) from "
                    f"{len(findings)} finding(s), mode={self.mode}"),
        ))
        return rows

    def _handle(self, finding):
        subject = str(finding.get("subject", ""))
        before = finding.get("evidence")

        if self.breaker_tripped(subject):
            detail = (f"circuit breaker OPEN for {self.problem_key}/{subject} "
                      f"after {BREAKER_THRESHOLD} consecutive failures — "
                      f"operator must clear")
            try:
                self.store.raise_alarm(f"remediator:{self.name}",
                                       self.problem_key, detail)
            except Exception:
                pass
            return self._log(OUTCOME_TRIPPED, subject=subject,
                             before=before, detail=detail)

        used = self.attempts_used(subject)
        if used >= MAX_ATTEMPTS_24H:
            detail = (f"attempt cap reached ({used}/{MAX_ATTEMPTS_24H} in 24h) "
                      f"for {self.problem_key}/{subject} — opening operator card "
                      f"instead of attempt {used + 1}")
            try:
                self.store.raise_alarm(f"remediator:{self.name}",
                                       self.problem_key, detail)
            except Exception:
                pass
            return self._log(OUTCOME_ESCALATED, subject=subject,
                             attempt_n=used + 1, before=before, detail=detail)

        if self.mode == MODE_OBSERVE:
            return self._log(
                OUTCOME_OBSERVED, subject=subject, attempt_n=used + 1,
                action=self.describe(finding), before=before,
                detail="observe-only: nothing was changed",
            )

        try:
            action = self.act(finding) or self.describe(finding)
        except Exception as exc:
            return self._log(OUTCOME_FAILED, subject=subject, attempt_n=used + 1,
                             action=self.describe(finding), before=before,
                             detail=f"act raised: {exc}\n{traceback.format_exc()[:800]}")

        # EVIDENCE OR IT DID NOT HAPPEN: re-measure the same signal.
        try:
            after = self.measure(subject)
        except Exception as exc:
            return self._log(OUTCOME_FAILED, subject=subject, attempt_n=used + 1,
                             action=action, before=before,
                             detail=f"could not re-measure after acting: {exc}")

        if not self.cleared(before, after):
            return self._log(OUTCOME_FAILED, subject=subject, attempt_n=used + 1,
                             action=action, before=before, after=after,
                             detail="action dispatched but the signal did not clear")

        return self._log(OUTCOME_ACTED, subject=subject, attempt_n=used + 1,
                         action=action, before=before, after=after,
                         detail="signal re-measured and clear")

    # -- subclass surface -----------------------------------------------------

    def describe(self, finding):
        return f"{self.name}:{finding.get('subject', '')}"

    def detect(self):
        return []

    def act(self, finding):
        return ""

    def measure(self, subject):
        return {}

    def cleared(self, before, after):
        """Default: the signal is clear when re-measurement finds nothing."""
        return not after


def assert_cannot_self_block(remediator):
    """Property 3, enforced at construction rather than in a comment.

    A remediator that guards a gate AND creates queued work is exactly the
    _self_heal_qa deadlock: the work it queues holds the gate it is waiting on,
    forever.
    """
    if remediator.guards_gate and remediator.creates_queue_work:
        raise SelfBlockingRemediator(
            f"{remediator.name} guards gate {remediator.guards_gate!r} and also "
            f"creates queued work — that is the deadlock that caused the "
            f"17-day release outage. Split it into a detector and a separate, "
            f"operator-approved fix."
        )
    return True


# ── the four remediators ─────────────────────────────────────────────────────

class StaleHostRemediator(Remediator):
    """A host more than N commits behind master keeps claiming work.

    Pauses it in `controls` and alarms. Escalates only if the host STILL claims
    work after the pause — a pause that did not take is the interesting case.
    DB-side enforcement belongs to runner/stale_host_guard.py; this does not
    duplicate it, it only flips the control and observes the result.
    """

    name = "stale_host"
    problem_key = "host_behind_master"
    creates_queue_work = False

    def __init__(self, store, mode=None, now=None, max_behind=None):
        self.max_behind = int(max_behind if max_behind is not None
                              else os.environ.get("ORCH_STALE_HOST_MAX_BEHIND", "50"))
        super().__init__(store, mode=mode, now=now)

    def detect(self):
        rows = self.store.select("hosts", {
            "select": "host,commits_behind,claiming",
            "commits_behind": f"gt.{self.max_behind}",
            "limit": "50",
        })
        return [{"subject": r.get("host", ""), "evidence": dict(r)} for r in rows]

    def act(self, finding):
        host = finding.get("subject", "")
        self.store.update("controls", {"host": host},
                          {"paused": True, "paused_reason": "stale_host remediator"})
        return f"paused host {host} in controls"

    def measure(self, subject):
        rows = self.store.select("hosts", {
            "select": "host,commits_behind,claiming",
            "host": f"eq.{subject}", "limit": "1",
        })
        return rows[0] if rows else {}

    def cleared(self, before, after):
        # Success is "it stopped claiming", not "we sent the pause".
        return not after.get("claiming", False)


class HeldReleaseRemediator(Remediator):
    """A release gate held past ORCH_RELEASE_FIX_HOLD_MAX_H.

    Alarms and clears the stale fix lineage. It MUST NOT queue a fix task —
    that is precisely the loop that caused the outage — so
    `creates_queue_work` is False and `assert_cannot_self_block` refuses the
    class outright if anyone ever flips it.
    """

    name = "held_release"
    problem_key = "release_gate_held"
    creates_queue_work = False
    guards_gate = "release"

    def __init__(self, store, mode=None, now=None, max_hold_h=None):
        self.max_hold_h = float(max_hold_h if max_hold_h is not None
                                else os.environ.get("ORCH_RELEASE_FIX_HOLD_MAX_H", "6"))
        super().__init__(store, mode=mode, now=now)

    def detect(self):
        rows = self.store.select("release_holds", {
            "select": "id,project,held_since,fix_lineage,cleared",
            "cleared": "is.false",
            "limit": "50",
        })
        out = []
        for r in rows:
            if _hours_since(r.get("held_since"), self._now()) >= self.max_hold_h:
                out.append({"subject": str(r.get("id", "")), "evidence": dict(r)})
        return out

    def act(self, finding):
        hold_id = finding.get("subject", "")
        # Clear the LINEAGE, never queue a replacement fix.
        self.store.update("release_holds", {"id": hold_id},
                          {"fix_lineage": None, "cleared": True})
        return f"cleared stale fix lineage on release hold {hold_id} (queued nothing)"

    def measure(self, subject):
        rows = self.store.select("release_holds", {
            "select": "id,cleared,fix_lineage", "id": f"eq.{subject}", "limit": "1",
        })
        return rows[0] if rows else {}

    def cleared(self, before, after):
        return bool(after.get("cleared"))


class EvidenceGapRemediator(Remediator):
    """A task in a terminal success state with no artifact, log, outcome or commit.

    Moves it to PHANTOM_UNVERIFIED. Strictly one-directional: this never
    promotes anything TO a success state, so a bug here can only ever
    under-claim, never fabricate a merge.
    """

    name = "evidence_gap"
    problem_key = "terminal_success_without_evidence"
    creates_queue_work = False
    TERMINAL_SUCCESS = ("DONE", "MERGED")

    def detect(self):
        out = []
        for state in self.TERMINAL_SUCCESS:
            rows = self.store.select("tasks", {
                "select": "id,slug,state,note,commit_sha,artifact_url",
                "state": f"eq.{state}",
                "order": "updated_at.desc",
                "limit": "100",
            })
            for r in rows:
                if not _has_evidence(r):
                    out.append({"subject": str(r.get("id", "")), "evidence": dict(r)})
        return out

    def act(self, finding):
        task_id = finding.get("subject", "")
        note = ("evidence_gap remediator: terminal success with no artifact, log, "
                "outcome or commit — demoted to PHANTOM_UNVERIFIED for review")
        self.store.update("tasks", {"id": task_id},
                          {"state": "PHANTOM_UNVERIFIED", "note": note})
        return f"demoted task {task_id} to PHANTOM_UNVERIFIED"

    def measure(self, subject):
        rows = self.store.select("tasks", {
            "select": "id,state,commit_sha,artifact_url",
            "id": f"eq.{subject}", "limit": "1",
        })
        return rows[0] if rows else {}

    def cleared(self, before, after):
        return after.get("state") == "PHANTOM_UNVERIFIED"


class StrandedBranchRemediator(Remediator):
    """Agent branches still unmerged after N days.

    Requeues the ORIGINAL task, one at a time, at most MAX_REQUEUE_PER_RUN per
    run. Never a bulk sweep: the last bulk state change moved 9,236 tasks and
    made every downstream metric untrue.
    """

    name = "stranded_branch"
    problem_key = "branch_unmerged"
    #: This one DOES create queued work, which is exactly why it must not guard
    #: a gate. assert_cannot_self_block enforces that pairing.
    creates_queue_work = True
    guards_gate = None

    def __init__(self, store, mode=None, now=None, stale_days=None):
        self.stale_days = float(stale_days if stale_days is not None
                                else os.environ.get("ORCH_STRANDED_BRANCH_DAYS", "5"))
        super().__init__(store, mode=mode, now=now)

    def detect(self):
        rows = self.store.select("agent_branches", {
            "select": "branch,task_id,merged,created_at",
            "merged": "is.false",
            "order": "created_at.asc",
            "limit": str(MAX_REQUEUE_PER_RUN * 4),
        })
        out = []
        cutoff_h = self.stale_days * 24
        for r in rows:
            if _hours_since(r.get("created_at"), self._now()) >= cutoff_h:
                out.append({"subject": str(r.get("task_id", "")), "evidence": dict(r)})
            if len(out) >= MAX_REQUEUE_PER_RUN:
                break
        return out

    def act(self, finding):
        task_id = finding.get("subject", "")
        self.store.update("tasks", {"id": task_id}, {
            "state": "QUEUED",
            "note": "stranded_branch remediator: branch unmerged past the stale "
                    "window; requeued individually",
        })
        return f"requeued task {task_id}"

    def measure(self, subject):
        rows = self.store.select("tasks", {
            "select": "id,state", "id": f"eq.{subject}", "limit": "1",
        })
        return rows[0] if rows else {}

    def cleared(self, before, after):
        return after.get("state") == "QUEUED"


REMEDIATORS = (
    StaleHostRemediator,
    HeldReleaseRemediator,
    EvidenceGapRemediator,
    StrandedBranchRemediator,
)


# ── helpers ──────────────────────────────────────────────────────────────────

EVIDENCE_FIELDS = ("commit_sha", "artifact_url", "outcome_id", "log_url", "note")


def _has_evidence(row):
    """Any artifact, log, outcome, commit or note counts as evidence.

    Deliberately generous: this remediator DEMOTES on a miss, so a false
    negative costs a real success its state. Being wrong in the other
    direction only leaves a phantom in place for a human to notice.
    """
    for key in EVIDENCE_FIELDS:
        value = row.get(key)
        if isinstance(value, str):
            if value.strip():
                return True
        elif value:
            return True
    return False


def _hours_since(ts, now_epoch):
    """Hours between an ISO-ish timestamp and now. Unparseable == 0 hours.

    Fail-soft AND fail-closed: a timestamp we cannot read reports as brand new,
    so a parse bug can never make a remediator act on everything at once.
    """
    if not ts:
        return 0.0
    text = str(ts).replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            import datetime
            parsed = datetime.datetime.strptime(text[:32], fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return max(0.0, (now_epoch - parsed.timestamp()) / 3600.0)
        except Exception:
            continue
    return 0.0


def build(cls, store=None, mode=None, now=None, **kwargs):
    """Construct a remediator, wrapping the store when in observe mode."""
    resolved = mode if mode in _VALID_MODES else mode_for(cls.name)
    base = store if store is not None else Store()
    if resolved == MODE_OBSERVE:
        base = ObserveStore(base)
    return cls(base, mode=resolved, now=now, **kwargs)


def run(store=None):
    """Periodic entry point. Every remediator is OFF unless an operator says so."""
    summary = []
    for cls in REMEDIATORS:
        resolved = mode_for(cls.name)
        try:
            bot = build(cls, store=store, mode=resolved)
            rows = bot.run_cycle()
        except Exception as exc:
            print(f"[remediation] {cls.name}: cycle failed: {exc}")
            summary.append({"remediator": cls.name, "mode": resolved, "error": str(exc)})
            continue
        counts = {}
        for r in rows:
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        summary.append({"remediator": cls.name, "mode": resolved, "counts": counts})
        print(f"[remediation] {cls.name} mode={resolved} {json.dumps(counts, sort_keys=True)}")
    return summary


if __name__ == "__main__":
    run()
