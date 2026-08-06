"""Per-pass merge-train instrumentation.

WHY THIS EXISTS (2026-08-06)
---------------------------
A merge-train pass that merges nothing was indistinguishable from a pass that
never ran. Both produced the same thing: silence. That is the same class of
failure that hid the release deadlock for 17 days, and it made "75 approved
cards, zero merged" impossible to diagnose from the outside -- the counts in
train_run()'s summary say WHAT happened but never WHICH card or WHY.

The train already stamps a per-card verdict in approvals.decided_by
("train:TESTFAIL", "train:conflict-exhausted", ...). That is cumulative card
state, not a record of a pass. It cannot answer "did the train run at all in the
last hour, and what did it decide to do with each card it saw".

This module records exactly that, once per pass, and persists it. It never
raises: instrumentation that can break the train is worse than no
instrumentation.

CONTRACT
--------
Every card the pass considers must end in exactly one terminal bucket --
merged, failed, or skipped -- each with a reason for the non-merged cases.
`unaccounted()` reports any card that was considered and never resolved, so a
future refactor that adds a silent early-return shows up as a number instead of
as silence.
"""

import json
import os
import socket
import threading
import time
import uuid

import db

APP = "merge_train"

# A pass that ended before looking at any card records one of these instead of
# card buckets, so "never ran" is a first-class, queryable outcome.
NOT_RUN_REASONS = (
    "paused",
    "not-integration-owner",
    "lease-not-acquired",
    "no-cards",
)


def _host():
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


class PassReport:
    """Records what one merge-train pass considered, and why each card ended."""

    def __init__(self, trigger="scheduled"):
        self.pass_id = str(uuid.uuid4())
        self.trigger = str(trigger or "scheduled")
        self.host = _host()
        self.started = time.time()
        self.finished = None
        self._considered = []          # slugs, in order seen
        self._merged = []              # slugs
        self._failed = {}              # slug -> reason
        self._skipped = {}             # slug -> reason
        self._not_run = None           # str, when the pass never reached cards
        # process_project runs under a ThreadPoolExecutor, so every recorder is
        # called concurrently. "considered" is a membership test followed by an
        # append -- not atomic under the GIL.
        self._lock = threading.Lock()

    # ── recording ────────────────────────────────────────────────────────────
    def consider(self, slug):
        """Called once per card the pass takes responsibility for."""
        slug = str(slug or "").strip()
        if slug:
            with self._lock:
                if slug not in self._considered:
                    self._considered.append(slug)
        return slug

    def merged(self, slug):
        slug = str(slug or "").strip()
        if slug:
            self.consider(slug)
            with self._lock:
                self._failed.pop(slug, None)
                self._skipped.pop(slug, None)
                if slug not in self._merged:
                    self._merged.append(slug)

    def failed(self, slug, reason):
        """The card was attempted and the attempt lost (tests, build, conflict)."""
        slug = str(slug or "").strip()
        if slug:
            self.consider(slug)
            with self._lock:
                if slug not in self._merged:
                    self._failed[slug] = str(reason or "unspecified")[:300]

    def skipped(self, slug, reason):
        """The card was NOT attempted (cap, lock, pause, no branch, no task)."""
        slug = str(slug or "").strip()
        if slug:
            self.consider(slug)
            with self._lock:
                if slug not in self._merged and slug not in self._failed:
                    self._skipped[slug] = str(reason or "unspecified")[:300]

    def not_run(self, reason):
        """The pass ended before considering cards. Reason should be in NOT_RUN_REASONS."""
        self._not_run = str(reason or "unspecified")[:300]

    # ── derived ──────────────────────────────────────────────────────────────
    def unaccounted(self):
        """Cards considered but never resolved -- the silent-early-return detector."""
        resolved = set(self._merged) | set(self._failed) | set(self._skipped)
        return [s for s in self._considered if s not in resolved]

    def is_no_op(self):
        return not self._merged

    def no_op_reason(self):
        """Why this pass merged nothing. Never returns None when is_no_op() is true."""
        if not self.is_no_op():
            return None
        if self._not_run:
            return self._not_run
        if not self._considered:
            return "no-cards"
        stray = self.unaccounted()
        if stray:
            return f"unaccounted:{len(stray)} card(s) considered and never resolved"
        reasons = {}
        for r in list(self._failed.values()) + list(self._skipped.values()):
            key = r.split(":", 1)[0].strip() or "unspecified"
            reasons[key] = reasons.get(key, 0) + 1
        top = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
        return "all-cards-blocked: " + ", ".join(f"{k}={v}" for k, v in top)

    def to_dict(self):
        self.finished = self.finished or time.time()
        return {
            "pass_id": self.pass_id,
            "trigger": self.trigger,
            "host": self.host,
            "started_at": self.started,
            "duration_s": round(self.finished - self.started, 3),
            "considered": len(self._considered),
            "merged": len(self._merged),
            "failed": len(self._failed),
            "skipped": len(self._skipped),
            "unaccounted": len(self.unaccounted()),
            "no_op": self.is_no_op(),
            "no_op_reason": self.no_op_reason(),
            "not_run": self._not_run,
            "merged_slugs": self._merged[:50],
            "failed_reasons": dict(list(self._failed.items())[:50]),
            "skipped_reasons": dict(list(self._skipped.items())[:50]),
        }

    def summary_line(self):
        d = self.to_dict()
        line = (f"merge_train pass {d['pass_id'][:8]} ({d['trigger']}): "
                f"{d['considered']} considered, {d['merged']} merged, "
                f"{d['failed']} failed, {d['skipped']} skipped "
                f"in {d['duration_s']}s")
        if d["unaccounted"]:
            line += f" -- WARNING {d['unaccounted']} unaccounted"
        if d["no_op"]:
            line += f" -- MERGED NOTHING: {d['no_op_reason']}"
        return line

    # ── persistence ──────────────────────────────────────────────────────────
    def persist(self):
        """Write the pass to fleet_telemetry. Fail-soft: returns False on any error.

        One row per pass with the full detail in tags, plus flat metric rows so
        the counts are graphable without unpacking jsonb.
        """
        d = self.to_dict()
        if os.environ.get("ORCH_MERGE_TRAIN_REPORT", "true").lower() in ("false", "0", "no"):
            return False
        ok = True
        rows = [{"app": APP, "domain": "pass", "metric": "merge_train.pass",
                 "value": 1.0, "tags": d}]
        for metric in ("considered", "merged", "failed", "skipped", "unaccounted"):
            rows.append({"app": APP, "domain": "pass",
                         "metric": f"merge_train.{metric}",
                         "value": float(d[metric]),
                         "tags": {"pass_id": d["pass_id"], "host": d["host"]}})
        for row in rows:
            try:
                db.insert("fleet_telemetry", row)
            except Exception:
                ok = False
        try:
            print(self.summary_line(), flush=True)
        except Exception:
            pass
        return ok


def last_pass(within_minutes=90):
    """Most recent persisted pass, or None. Used by the health surface."""
    try:
        rows = db.select("fleet_telemetry", {
            "select": "timestamp,tags",
            "app": f"eq.{APP}",
            "metric": "eq.merge_train.pass",
            "order": "timestamp.desc",
            "limit": "1"}) or []
    except Exception:
        return None
    if not rows:
        return None
    tags = rows[0].get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = {}
    out = dict(tags or {})
    out["timestamp"] = rows[0].get("timestamp")
    return out
