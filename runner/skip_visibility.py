"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Skip Reason Visibility.

Every scheduler in this fleet can decline to run a job (drain mode, lean mode,
the kill switch, generator throttles, the velocity PID controller, a disabled
feature flag). Until now each of those decisions printed one line to stdout and
then vanished: `[sched] scout skipped - drain_mode=auto queue>=800`. Nothing
persisted it, so "why did nothing build for two hours?" was unanswerable after
the log rotated, and no build summary or API response carried the reason.

This module is the durable, structured side of that decision. A skip is
recorded once, classified into a stable category, given a concrete remedy a
developer can act on, and then rendered two ways:

  render_build_summary(...)  -> prominent human block for a build summary / UI
  api_payload(...)           -> JSON-safe dict for API responses

Pure and fail-soft by construction: classification takes a raw reason string and
nothing else, the store is a bounded in-process ring buffer, and every public
function returns a sensible default rather than raising. Recording a skip must
never be able to wedge the scheduler that is trying to skip.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

# Stable category vocabulary. Callers and dashboards may key off these strings,
# so they are additive-only: never rename one, add a new one instead.
CATEGORY_DRAIN = "drain"
CATEGORY_LEAN = "lean_mode"
CATEGORY_PAUSED = "paused"
CATEGORY_THROTTLE = "throttle"
CATEGORY_DISABLED = "disabled"
CATEGORY_VELOCITY = "velocity"
CATEGORY_BUDGET = "budget"
CATEGORY_DEPENDENCY = "dependency"
CATEGORY_UNKNOWN = "unknown"

# Remedies are the whole point of the feature: a skip reason that does not tell
# a developer what to do about it is not "actionable" visibility.
_REMEDIES: Dict[str, str] = {
    CATEGORY_DRAIN: (
        "Backlog drain is on. Let the queue fall below ORCH_DRAIN_QUEUE_FLOOR, "
        "or set ORCH_DRAIN_MODE=false to run this job anyway."
    ),
    CATEGORY_LEAN: (
        "Lean mode is on. Unset ORCH_LEAN_MODE or remove this job from the "
        "lean-mode skip list to restore it."
    ),
    CATEGORY_PAUSED: (
        "The fleet kill switch is engaged. Clear the pause before expecting "
        "token-spending jobs to run."
    ),
    CATEGORY_THROTTLE: (
        "Queue depth is above the generator ceiling. Drain the backlog or raise "
        "the generation ceiling if the depth is expected."
    ),
    CATEGORY_DISABLED: (
        "This job is gated off by a feature flag. Enable its ORCH_* flag to "
        "turn it back on."
    ),
    CATEGORY_VELOCITY: (
        "The queue-velocity controller paused this generator because the queue "
        "grew for consecutive windows. It resumes on its own once velocity "
        "turns negative."
    ),
    CATEGORY_BUDGET: (
        "The spend budget for this lane is exhausted. Raise the budget or wait "
        "for the next budget window."
    ),
    CATEGORY_DEPENDENCY: (
        "A prerequisite was missing or unavailable. Fix the dependency named in "
        "the reason, then re-run."
    ),
    CATEGORY_UNKNOWN: "Inspect the raw reason below; it has no registered remedy yet.",
}

# Ordered most-specific-first: the first pattern that matches wins.
_PATTERNS = (
    (CATEGORY_DRAIN, re.compile(r"drain", re.I)),
    (CATEGORY_LEAN, re.compile(r"lean[_\s-]?mode", re.I)),
    (CATEGORY_VELOCITY, re.compile(r"velocity", re.I)),
    (CATEGORY_PAUSED, re.compile(r"\bpaused?\b|kill[_\s-]?switch", re.I)),
    (CATEGORY_THROTTLE, re.compile(r"throttl|ceiling|queue depth", re.I)),
    (CATEGORY_BUDGET, re.compile(r"budget|spend cap|out of (?:tokens|credit)", re.I)),
    (CATEGORY_DEPENDENCY, re.compile(r"no project|unavailable|missing|not found", re.I)),
    (CATEGORY_DISABLED, re.compile(r"disabled|\boff\b|not enabled", re.I)),
)

_MAX_RECORDS_DEFAULT = 200


@dataclass
class SkipRecord:
    """One durable, structured skip decision."""

    job: str
    raw_reason: str
    category: str
    remedy: str
    at: str
    detail: str = ""
    context: Dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)

    def one_line(self) -> str:
        head = "%s skipped - %s" % (self.job, self.raw_reason or "(no reason given)")
        return "%s [%s]" % (head, self.category)


def classify(raw_reason: Optional[str]) -> str:
    """Map a free-text skip reason onto the stable category vocabulary."""
    text = str(raw_reason or "").strip()
    if not text:
        return CATEGORY_UNKNOWN
    for category, pattern in _PATTERNS:
        try:
            if pattern.search(text):
                return category
        except Exception:
            continue
    return CATEGORY_UNKNOWN


def remedy_for(category: Optional[str]) -> str:
    """The actionable next step for a category. Never raises, never empty."""
    return _REMEDIES.get(str(category or ""), _REMEDIES[CATEGORY_UNKNOWN])


def build_record(job: str, raw_reason: Optional[str], *, context=None, at=None) -> SkipRecord:
    """Pure constructor: raw scheduler output -> structured record. No I/O."""
    category = classify(raw_reason)
    stamp = at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    ctx = {}
    for key, value in (context or {}).items():
        try:
            ctx[str(key)] = str(value)
        except Exception:
            continue
    return SkipRecord(
        job=str(job or "unknown-job"),
        raw_reason=str(raw_reason or "").strip(),
        category=category,
        remedy=remedy_for(category),
        at=stamp,
        detail=_detail_for(category, raw_reason),
        context=ctx,
    )


def _detail_for(category: str, raw_reason: Optional[str]) -> str:
    text = str(raw_reason or "").strip()
    if category == CATEGORY_DRAIN:
        floor = re.search(r"queue>=(\d+)", text)
        if floor:
            return "Backlog drain active; queue is at or above %s." % floor.group(1)
        return "Backlog drain active."
    if category == CATEGORY_UNKNOWN and not text:
        return "The scheduler declined to run this job but reported no reason."
    return text


class SkipLedger:
    """Bounded, thread-safe in-process store of recent skip decisions.

    Deliberately memory-only: a skip is an operational signal, not a durable
    business fact, and the scheduler paths that record skips must never block on
    disk or network.
    """

    def __init__(self, max_records: Optional[int] = None):
        self._lock = threading.Lock()
        self._records: List[SkipRecord] = []
        self._max = max_records or _env_max_records()

    def record(self, job: str, raw_reason: Optional[str], *, context=None, at=None) -> SkipRecord:
        rec = build_record(job, raw_reason, context=context, at=at)
        with self._lock:
            self._records.append(rec)
            overflow = len(self._records) - max(1, self._max)
            if overflow > 0:
                del self._records[:overflow]
        return rec

    def recent(self, limit: Optional[int] = None, *, job: Optional[str] = None,
               category: Optional[str] = None) -> List[SkipRecord]:
        with self._lock:
            items = list(self._records)
        if job:
            items = [r for r in items if r.job == job]
        if category:
            items = [r for r in items if r.category == category]
        if limit is not None and limit >= 0:
            items = items[-limit:]
        return items

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)


def _env_max_records() -> int:
    try:
        return max(1, int(os.environ.get("ORCH_SKIP_LEDGER_MAX", str(_MAX_RECORDS_DEFAULT))))
    except Exception:
        return _MAX_RECORDS_DEFAULT


_ledger = SkipLedger()


def record(job: str, raw_reason: Optional[str], *, context=None, at=None) -> Optional[SkipRecord]:
    """Module-level entry point used by schedulers. Fail-soft: returns None on error."""
    try:
        return _ledger.record(job, raw_reason, context=context, at=at)
    except Exception:
        return None


def note_skip(job: str, reason: Optional[str], context=None, logger=None) -> Optional[SkipRecord]:
    """Single recording chokepoint for schedulers.

    Same contract as :func:`record`, plus an optional ``logger`` so a caller can
    see why bookkeeping failed without that failure ever propagating. A skip
    must always be allowed to happen even if recording it does not.
    """
    try:
        return _ledger.record(job, reason, context=context)
    except Exception as exc:  # pragma: no cover - defensive
        if logger is not None:
            try:
                logger.debug("skip_visibility.note_skip failed: %s", exc)
            except Exception:
                pass
        return None


def recent(limit: Optional[int] = None, *, job: Optional[str] = None,
           category: Optional[str] = None) -> List[SkipRecord]:
    try:
        return _ledger.recent(limit, job=job, category=category)
    except Exception:
        return []


def clear() -> None:
    try:
        _ledger.clear()
    except Exception:
        pass


def summarize(records: Optional[Iterable[SkipRecord]] = None) -> Dict[str, object]:
    """Aggregate skip records for a build summary / dashboard tile."""
    try:
        items = list(records) if records is not None else recent()
    except Exception:
        items = []
    by_category: Dict[str, int] = {}
    by_job: Dict[str, int] = {}
    for rec in items:
        by_category[rec.category] = by_category.get(rec.category, 0) + 1
        by_job[rec.job] = by_job.get(rec.job, 0) + 1
    dominant = ""
    if by_category:
        dominant = max(sorted(by_category), key=lambda k: by_category[k])
    return {
        "total": len(items),
        "by_category": by_category,
        "by_job": by_job,
        "dominant_category": dominant,
        "dominant_remedy": remedy_for(dominant) if dominant else "",
    }


def render_build_summary(records: Optional[Iterable[SkipRecord]] = None, *, limit: int = 10) -> str:
    """Prominent, human-readable block for the build summary and the UI.

    Returns a clear "nothing was skipped" line rather than an empty string, so a
    summary never silently omits the section and leaves a developer guessing.
    """
    try:
        items = list(records) if records is not None else recent()
    except Exception:
        items = []
    if not items:
        return "SKIPPED STEPS: none - every scheduled job ran."

    stats = summarize(items)
    lines = ["SKIPPED STEPS (%d)" % stats["total"]]
    counts = stats["by_category"] or {}
    if counts:
        breakdown = ", ".join("%s=%d" % (k, counts[k]) for k in sorted(counts))
        lines.append("  by reason: %s" % breakdown)
    shown = items[-limit:] if limit and limit > 0 else items
    for rec in shown:
        lines.append("  - %s" % rec.one_line())
        if rec.detail and rec.detail != rec.raw_reason:
            lines.append("      %s" % rec.detail)
        lines.append("      fix: %s" % rec.remedy)
    hidden = len(items) - len(shown)
    if hidden > 0:
        lines.append("  ... and %d earlier skip(s)" % hidden)
    return "\n".join(lines)


def api_payload(records: Optional[Iterable[SkipRecord]] = None, *, limit: int = 50) -> Dict[str, object]:
    """JSON-safe payload for API responses that report a build's skipped steps."""
    try:
        items = list(records) if records is not None else recent()
    except Exception:
        items = []
    shown = items[-limit:] if limit and limit > 0 else items
    return {
        "skipped": [rec.as_dict() for rec in shown],
        "summary": summarize(items),
        "rendered": render_build_summary(items, limit=limit),
    }
