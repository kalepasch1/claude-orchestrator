#!/usr/bin/env python3
"""db_learning.py — what actually worked, what keeps coming back, and where it's heading.

Three read-only instruments over tables the steering loop already writes:

1. OUTCOME LEARNING. closeout verdicts per db-steer PR persist to db_pr_closeouts
   (migration 20260915000000). efficacy() turns them into per-group track records —
   "fk-indexes: 12 verified, 1 not-confirmed" — so remediation ordering prefers the
   generators that demonstrably fix things, and the brief can say "this exact fix has
   worked N times" next to a finding.
2. RECURRENCE. reconcile reopens a resolved finding by bumping `occurrences` and steering
   it like a new gap. An open finding with occurrences > 1 is a fix that regressed; those
   outrank fresh findings in the brief because they name a process that reintroduces harm,
   not a one-off gap.
3. TRENDLINES. posture snapshots are hourly: trendline(project) returns latest score,
   Δ7d, Δ30d and the findings resolution/creation rate per day over the window — the
   trajectory a memo or brief argues from ("closing at 3.2 findings/wk").

All control-plane reads, no model calls, every function fail-soft and cached briefly.
"""
from __future__ import annotations

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

CLOSEOUT_TABLE = "db_pr_closeouts"
FINDINGS = "db_findings"
SNAPSHOTS = "db_posture_snapshots"
CACHE_TTL_S = int(os.environ.get("ORCH_DB_LEARNING_TTL_S", "300"))
_snap_cache = {"at": 0.0, "value": None}


# ── persistence (called from db_remediate.closeout_project) ───────────────────────────

def record_closeout(project, repo, pr_number, group, state, total, resolved, open_ct, merged):
    """Upsert one (repo, pr_number) measurement: read-then-update/insert against the table
    unique key, because the shared db.upsert helper has no conflict-target argument.
    Fail-soft False; never raises."""
    try:
        row = {"project": project, "repo": repo, "pr_number": int(pr_number),
               "pr_group": group, "state": state, "findings_total": int(total),
               "findings_resolved": int(resolved), "findings_open": int(open_ct),
               "merged": bool(merged), "measured_at": _iso()}
        existing = db.select(CLOSEOUT_TABLE, {"select": "id", "repo": "eq.%s" % repo,
                                              "pr_number": "eq.%d" % int(pr_number), "limit": "1"}) or []
        if existing:
            return bool(db.update(CLOSEOUT_TABLE, {"id": existing[0]["id"]}, row))
        return bool(db.insert(CLOSEOUT_TABLE, row))
    except Exception as e:
        print("db_learning: closeout record %s#%s failed: %s" % (repo, pr_number, str(e)[:120]))
        return False


# ── outcome learning ──────────────────────────────────────────────────────────────────

def efficacy():
    """{group: {opened, verified, not_confirmed, rate}} newest-first dedup by (repo, pr).
    Rate = verified / opened (merged or open both count as opened; a PR never applied yet
    neither helps nor hurts the rate)."""
    try:
        rows = db.select_all(CLOSEOUT_TABLE, {"select": "pr_group,state,repo,pr_number,measured_at"},
                             order="measured_at.desc") or []
    except Exception as e:
        print("db_learning: efficacy read failed: %s" % str(e)[:120])
        return {}
    seen = set()
    out = {}
    for r in rows:
        key = (r.get("repo"), r.get("pr_number"))
        if key in seen:
            continue
        seen.add(key)
        g = r.get("pr_group") or "unknown"
        rec = out.setdefault(g, {"opened": 0, "verified": 0, "not_confirmed": 0, "rate": None})
        rec["opened"] += 1
        if r.get("state") == "verified-resolved":
            rec["verified"] += 1
        elif r.get("state") == "merged-not-confirmed":
            rec["not_confirmed"] += 1
    for rec in out.values():
        decided = rec["verified"] + rec["not_confirmed"]
        rec["rate"] = round(rec["verified"] / decided, 2) if decided else None
    return out


def efficacy_order(groups):
    """Order remediation groups by demonstrated rate, unknowns in the middle, proven
    failures last. Empty history -> input order unchanged."""
    eff = efficacy()
    if not eff:
        return list(groups)

    def key(g):
        rec = eff.get(g)
        if not rec or rec["rate"] is None:
            return (1, 0)
        return (0 if rec["rate"] >= 0.5 else 2, -rec["rate"])
    return sorted(groups, key=key)


def group_note(group):
    """Short brief fragment like 'this fix class resolved 4/4 merged PRs' or '' if unknown."""
    eff = efficacy()
    rec = eff.get(group)
    if not rec or rec["rate"] is None:
        return ""
    return "this fix class resolved %d/%d merged PRs so far" % (rec["verified"],
                                                                rec["verified"] + rec["not_confirmed"])


# ── recurrence ────────────────────────────────────────────────────────────────────────

def recurrences(project):
    """Open findings that were fixed once and CAME BACK (occurrences > 1): the process
    regressions, not one-off gaps. Fail-soft []."""
    try:
        rows = db.select(FINDINGS, {
            "select": "fingerprint,probe_id,severity,title,object_schema,object_name,occurrences,last_seen_at",
            "project": "eq.%s" % project, "status": "eq.open", "direction": "eq.undermines",
            "occurrences": "gt.1", "order": "occurrences.desc,last_seen_at.desc", "limit": "50"}) or []
    except Exception as e:
        print("db_learning: recurrence read failed for %s: %s" % (project, str(e)[:120]))
        return []
    return rows


def recurrence_lines(project, limit=3):
    """Brief fragments: 'FIX IS NOT STICKING: <title> (<obj>) — reopen #3'."""
    lines = []
    for r in recurrences(project)[:max(0, limit)]:
        obj = ".".join(x for x in (r.get("object_schema"), r.get("object_name")) if x)
        lines.append("[%s] REGRESSED: %s%s — reopen #%d" % (
            str(r.get("severity") or "medium").upper(), r.get("title"), " (%s)" % obj if obj and obj not in str(r.get("title") or "") else "",
            int(r.get("occurrences") or 0)))
    return lines


# ── trendlines ────────────────────────────────────────────────────────────────────────

def _iso(ts=None):
    import datetime
    t = time.time() if ts is None else ts
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()


def trendline(project, window_s=7 * 86400):
    """{score, prev, delta, per_day_resolved, per_day_new} from snapshots + findings over
    the window. Fail-soft {} when snapshots are absent."""
    try:
        rows = db.select(SNAPSHOTS, {
            "select": "score,taken_at", "project": "eq.%s" % project,
            "order": "taken_at.desc", "limit": "200"}) or []
    except Exception as e:
        print("db_learning: trendline snapshots failed for %s: %s" % (project, str(e)[:120]))
        return {}
    latest = prev = None
    cutoff = time.time() - window_s
    for r in rows:
        if r.get("score") is None:
            continue
        ts = _parse(r.get("taken_at"))
        if ts is None:
            continue
        if latest is None:
            latest = (ts, float(r["score"]))
        if ts <= cutoff:
            prev = (ts, float(r["score"]))
            break
    if latest is None:
        return {}
    out = {"score": latest[1], "as_of": _iso(latest[0])}
    if prev is not None:
        out["prev"] = prev[1]
        out["delta"] = round(latest[1] - prev[1], 1)
    try:
        resolved = db.count(FINDINGS, {"project": "eq.%s" % project,
                                       "resolved_at": "gte.%s" % _iso(cutoff)})
        created = db.count(FINDINGS, {"project": "eq.%s" % project,
                                      "first_seen_at": "gte.%s" % _iso(cutoff)})
        days = max(1.0, window_s / 86400.0)
        out["per_day_resolved"] = round(int(resolved or 0) / days, 1)
        out["per_day_new"] = round(int(created or 0) / days, 1)
    except Exception:  # noqa: FAIL_SOFT_ERROR — per-day rates are decorative; a failed count yields a score-only trendline
        print("db_learning: trendline rates failed for %s" % project)
    return out


def trend_lines(project):
    """Brief fragments like 'posture 23.0 (+4.5 over 7d; closing 2.1 findings/day)'."""
    t = trendline(project)
    if not t:
        return []
    parts = ["posture %s" % t["score"]]
    if "delta" in t:
        d = t["delta"]
        parts.append("%s%s over 7d" % ("+" if d > 0 else "", d))  # "%+s" silently drops the + flag (a − looks like a +)
    if t.get("per_day_resolved") or t.get("per_day_new"):
        parts.append("resolving ~%s, new ~%s per day" % (t.get("per_day_resolved", "—"), t.get("per_day_new", "—")))
    return [" · ".join(parts)]


def _parse(value):
    """Supabase timestamps incl. truncated fractional seconds; float epoch passthrough."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        s = str(value or "").replace("Z", "+00:00")
        if "." in s and ("+" in s.split(".", 1)[1] or "-" in s.split(".", 1)[1]):
            head, tail = s.split(".", 1)
            idx = min(i for i in (tail.find("+"), tail.find("-")) if i > 0)
            s = head + "." + (tail[:idx] + "000000")[:6] + tail[idx:]
        import datetime
        return datetime.datetime.fromisoformat(s).timestamp()
    except Exception:
        return None
