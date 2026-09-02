#!/usr/bin/env python3
"""
pause_ttl.py - make a "temporary" pause prove it is still temporary.

THE FAILURE THIS EXISTS FOR
---------------------------
Audited 2026-08-30. Every pause holding the fleet down was written as temporary
and none was ever lifted:

  global        2026-08-24   "executor outage: every hosted provider is out of credit"
  apparently    2026-08-08   "manual improvement-restart 2026-08-09 (reversible)"
  tomorrow      2026-08-15   "Bear: fleet merging unreviewed agent branches ..."
  9 projects    2026-08-24   "controlled fleet verification ... REVERSIBLE - lifted when ..."

apparently sat paused for 22 days behind the word "(reversible)". Downstream,
merge_train ran 532 consecutive passes that considered 0 branches and merged 0,
and 1,848 agent commits stranded across two repos. Nothing was broken. Nobody
had lifted a hold that read, in the table, exactly like a deliberate one.

WHY THIS DOES NOT AUTO-RESUME
-----------------------------
The obvious fix - expire the pause and let work flow again - is the wrong one and
would be worse than the bug. A pause is the one control that stops spend and
stops autonomous merging. "executor outage: out of credit" is a pause that MUST
outlive its stated window; self-lifting it burns money against dead providers.
A pause is lifted by a person who has checked the reason still does not hold.

So this module changes what an operator SEES, never what the fleet DOES:
`is_paused()` is untouched, and nothing here writes `paused`. An expired TTL is
a question to answer, not a decision already taken.

STORAGE
-------
`controls` has no expires_at column, and a schema migration is not worth it for a
timestamp. The expiry rides in `reason` as a parseable marker:

    manual improvement-restart [expires 2026-09-06T12:00:00Z]

Unmarked reasons still classify: language like "temporary" or "reversible" is a
stated intent to lift, so a pause carrying it with no TTL is reported as
UNBOUNDED rather than quietly treated as deliberate.
"""
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

EXPIRY_RE = re.compile(r"\[expires\s+([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8})Z\]")

# Words an author uses when they mean to come back and lift this.
TEMPORARY_RE = re.compile(
    r"\b(temporar\w*|reversib\w*|revert\w*|for now|short[- ]lived|until\b|"
    r"manual (?:restart|improvement-restart)|controlled \w+ verification|"
    r"drain before|lifted when|re-?enable)\b", re.I)

# A pause with no TTL and no temporary language, older than this, is still worth
# a line in the report - not because it is wrong, but because "deliberate" should
# be a decision someone re-confirms rather than one that simply never came up.
DELIBERATE_REVIEW_DAYS = float(os.environ.get("ORCH_PAUSE_REVIEW_DAYS", "30"))

EXPIRED = "EXPIRED"
UNBOUNDED = "UNBOUNDED"
WITHIN_TTL = "WITHIN_TTL"
DELIBERATE = "DELIBERATE"
STALE_DELIBERATE = "STALE_DELIBERATE"


def embed_expiry(reason, ttl_hours, now=None):
    """Return `reason` with an [expires ...] marker appended (idempotent)."""
    if not ttl_hours:
        return reason
    now = now or datetime.datetime.utcnow()
    at = (now + datetime.timedelta(hours=float(ttl_hours))).replace(microsecond=0)
    return "%s [expires %sZ]" % (EXPIRY_RE.sub("", reason or "").strip(),
                                 at.isoformat())


def parse_expiry(reason):
    """Datetime from an [expires ...] marker, or None."""
    m = EXPIRY_RE.search(reason or "")
    if not m:
        return None
    try:
        return datetime.datetime.fromisoformat(m.group(1))
    except ValueError:
        return None


def _strptime_or_none(text, fmt):
    try:
        return datetime.datetime.strptime(text, fmt)
    except ValueError:
        return None


def _parse_ts(value):
    if not value:
        return None
    text = str(value).replace("Z", "").split("+")[0]
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        parsed = _strptime_or_none(text, fmt)
        if parsed is not None:
            return parsed
    return None


def classify(row, now=None):
    """(verdict, age_days, expires_at) for one paused controls row."""
    now = now or datetime.datetime.utcnow()
    reason = row.get("reason") or ""
    set_at = _parse_ts(row.get("updated_at"))
    age = (now - set_at).total_seconds() / 86400.0 if set_at else None

    expires = parse_expiry(reason)
    if expires:
        return (EXPIRED if now >= expires else WITHIN_TTL), age, expires
    if TEMPORARY_RE.search(reason):
        return UNBOUNDED, age, None
    if age is not None and age >= DELIBERATE_REVIEW_DAYS:
        return STALE_DELIBERATE, age, None
    return DELIBERATE, age, None


def _latest_paused_rows(rows):
    """Latest decision per (scope, project), keeping only the ones still paused.

    `controls` is append-friendly: an old paused row can sit behind a newer
    resume for the same scope. Reporting the stale row would invent a pause that
    is not in effect - the same latest-wins rule kill_switch.is_paused() uses.
    """
    seen = {}
    for r in sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True):
        key = (r.get("scope"), r.get("project"))
        if key not in seen:
            seen[key] = r
    return [r for r in seen.values() if r.get("paused")]


def stale_pauses(now=None, rows=None):
    """Every pause in effect, newest first, with a verdict on its stated intent."""
    if rows is None:
        rows = db.select("controls", {
            "select": "scope,project,paused,reason,updated_at,updated_by",
            "order": "updated_at.desc"}) or []
    out = []
    for r in _latest_paused_rows(rows):
        verdict, age, expires = classify(r, now)
        out.append({
            "scope": r.get("scope"), "project": r.get("project"),
            "verdict": verdict, "age_days": age, "expires_at": expires,
            "updated_by": r.get("updated_by"),
            "reason": (r.get("reason") or "").strip(),
        })
    out.sort(key=lambda d: -(d["age_days"] or 0))
    return out


NEEDS_ATTENTION = (EXPIRED, UNBOUNDED, STALE_DELIBERATE)


def report(now=None, rows=None):
    items = stale_pauses(now=now, rows=rows)
    if not items:
        return "pause_ttl: nothing is paused."
    lines = ["pause_ttl: %d pause(s) in effect" % len(items), ""]
    for d in items:
        lines.append("  %-16s %-28s %5.1fd  %s" % (
            d["verdict"], "%s/%s" % (d["scope"], d["project"] or "-"),
            d["age_days"] or 0.0, (d["updated_by"] or "?")))
        lines.append("      %s" % (d["reason"][:150] or "(no reason given)"))
    flagged = [d for d in items if d["verdict"] in NEEDS_ATTENTION]
    lines.append("")
    lines.append("%d of %d need a decision (EXPIRED / UNBOUNDED / STALE_DELIBERATE)."
                 % (len(flagged), len(items)))
    lines.append("Nothing here resumes on its own - lift with:")
    lines.append("  python3 runner/kill_switch.py  (or kill_switch.resume(scope, project))")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
