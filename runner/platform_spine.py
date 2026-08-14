#!/usr/bin/env python3
"""platform_spine.py — cross-app + pipeline CONTRACTS (Wave C, slice 3; Parts 6 & 7).

IMPROVEMENTS_MASTER_UNQUEUED_2026-07-31.md:

  Part 6 — "Matter spine (intake, triage, licensing, filings, video, newsletters keyed to one
  matter record — inbox, portal, and Foulkon exposure model are three views of one truth);
  exposure-to-hedge flywheel metric (% of quantified expected_loss_usd hedgeable on Tomorrow
  ... unhedgeable exposure auto-feeds the instrument foundry); renewal annuity engine (every
  filing schedules its own renewal/reporting calendar wired to the ambient monitor)."

  Part 7 — "Initiative-level integration (merge unit = initiative, not branch; one card judges
  a coherent changeset; thousands of merge decisions collapse to dozens); disposition memory
  (branch closures train dedupe + planner so duplicate work stops being GENERATED)."

This slice defines the CONTRACTS. Per-app surfaces are built by their own shards, and they
build against what is here rather than each inventing its own shape — which is the failure
these two Parts are both really about:

  * Part 6's matter spine exists because the same matter currently has a different identity in
    the inbox, the portal and the exposure model, so nothing can be reconciled across them.
  * Part 7's initiative merge unit exists because judging branches one at a time produces
    thousands of decisions on fragments of coherent changesets — this session alone stacked
    four branches that only make sense together.
  * Disposition memory exists because a closed duplicate teaches nothing today, so the planner
    generates the same duplicate again next week. Closing work is cheap; NOT GENERATING it is
    the compounding win.

Pure functions over plain data: no DB, no network, no clock except through an injected `now`.
Fail-soft per CLAUDE.md — bad input returns a sensible default, never raises.
"""
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONTRACT_VERSION = "1.0.0"

# ── Part 6a: the matter spine ───────────────────────────────────────────────────────────────

#: The surfaces that are VIEWS of a matter, never owners of one.
MATTER_VIEWS = ("inbox", "portal", "exposure")

#: Everything that keys to a matter rather than carrying its own identity.
MATTER_ARTIFACTS = ("intake", "triage", "licensing", "filing", "video", "newsletter")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(value):
    return _SLUG_STRIP.sub("-", str(value or "").strip().lower()).strip("-")


def matter_key(org=None, subject=None, jurisdiction=None):
    """Stable identity for a matter across every app and surface.

    Derived, not allocated: three apps that have never spoken to each other must arrive at the
    same key for the same matter, which an autoincrement id can never guarantee. Returns "" when
    there is not enough to identify anything — an empty key is safe, a colliding one is not.
    """
    try:
        parts = [_slug(org), _slug(subject), _slug(jurisdiction)]
        if not parts[0] or not parts[1]:
            return ""
        basis = "|".join(parts)
        digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
        return f"m-{parts[0][:24]}-{digest}"
    except Exception:
        return ""


def attach(matter_key_value, artifact_type, artifact_id):
    """A spine edge: this artifact belongs to this matter. Never raises."""
    try:
        artifact_type = str(artifact_type or "").lower()
        if not matter_key_value or not artifact_id:
            return None
        if artifact_type not in MATTER_ARTIFACTS:
            return None
        return {"matter": matter_key_value, "type": artifact_type, "id": str(artifact_id)}
    except Exception:
        return None


def views_agree(records):
    """Do the inbox, portal and exposure views describe the same matter?

    `records` maps view name -> {"matter": key, ...}. Returns
    {"agree", "matters", "missing_views", "reason"}.

    Disagreement here is the Part 6 problem in its observable form: three systems each certain
    they are looking at the matter, and no two of them at the same one. Never raises.
    """
    result = {"agree": False, "matters": [], "missing_views": [], "reason": ""}
    try:
        records = records or {}
        keys = set()
        for view in MATTER_VIEWS:
            record = records.get(view)
            key = (record or {}).get("matter") if isinstance(record, dict) else None
            if not key:
                result["missing_views"].append(view)
            else:
                keys.add(key)
        result["matters"] = sorted(keys)
        if result["missing_views"]:
            result["reason"] = ("no matter key from " + ", ".join(result["missing_views"])
                                + " — that view cannot be reconciled with the others")
            return result
        if len(keys) > 1:
            result["reason"] = ("the views disagree: " + ", ".join(sorted(keys))
                                + " — three systems, three different matters")
            return result
        result["agree"] = True
        return result
    except Exception:
        result["reason"] = "views could not be compared"
        return result


# ── Part 6b: the exposure-to-hedge flywheel ─────────────────────────────────────────────────

def hedge_flywheel(exposures, now=None):
    """% of quantified expected loss that is hedgeable, plus what is not.

    `exposures` are dicts: {"id", "expected_loss_usd", "hedgeable": bool, "instrument": str|None}.

    Three audiences, one number, which is why it is computed once here: it is a product-gap
    tracker, a demand signal, and an investor statistic. The unhedgeable remainder is not a
    rounding error to be dropped — it IS the instrument foundry's backlog, so it is returned
    itemised and ranked by size rather than summarised away.

    Never raises.
    """
    report = {
        "quantified_usd": 0.0,
        "hedgeable_usd": 0.0,
        "unhedgeable_usd": 0.0,
        "hedgeable_ratio": None,
        "foundry_backlog": [],
        "unquantified": 0,
    }
    try:
        for exposure in exposures or ():
            if not isinstance(exposure, dict):
                continue
            try:
                amount = float(exposure.get("expected_loss_usd"))
            except (TypeError, ValueError):
                report["unquantified"] += 1
                continue
            if amount != amount or amount <= 0:      # NaN or non-positive
                report["unquantified"] += 1
                continue
            report["quantified_usd"] += amount
            if exposure.get("hedgeable") is True and exposure.get("instrument"):
                report["hedgeable_usd"] += amount
            else:
                report["unhedgeable_usd"] += amount
                report["foundry_backlog"].append({
                    "id": exposure.get("id"),
                    "expected_loss_usd": amount,
                    "reason": ("no instrument named" if exposure.get("hedgeable") is True
                               else "not hedgeable on Tomorrow today"),
                })
        if report["quantified_usd"] > 0:
            report["hedgeable_ratio"] = round(
                report["hedgeable_usd"] / report["quantified_usd"], 4)
        report["foundry_backlog"].sort(key=lambda e: -e["expected_loss_usd"])
        for key in ("quantified_usd", "hedgeable_usd", "unhedgeable_usd"):
            report[key] = round(report[key], 2)
    except Exception:
        pass
    return report


# ── Part 6c: the renewal annuity engine ─────────────────────────────────────────────────────

#: Days before a due date at which the ambient monitor should already be watching.
DEFAULT_LEAD_DAYS = int(os.environ.get("ORCH_RENEWAL_LEAD_DAYS", "60"))


def renewal_schedule(filing, horizon_years=3, lead_days=None):
    """Every filing schedules its own renewals and reports. Never raises.

    A filing that does not schedule its own renewal is a filing someone has to remember, and
    the whole point of an annuity engine is that nobody has to. Returns a list of
    {"matter", "kind", "due_at", "watch_from", "sequence"} sorted by due date.
    """
    lead_days = DEFAULT_LEAD_DAYS if lead_days is None else lead_days
    out = []
    try:
        import datetime

        filing = filing if isinstance(filing, dict) else {}
        effective = filing.get("effective_at")
        if not effective:
            return []
        try:
            start = datetime.datetime.fromisoformat(str(effective).replace("Z", "+00:00"))
        except Exception:
            return []
        if start.tzinfo is None:
            start = start.replace(tzinfo=datetime.timezone.utc)

        cadences = []
        renewal_months = filing.get("renewal_months")
        if renewal_months:
            cadences.append(("renewal", int(renewal_months)))
        report_months = filing.get("report_months")
        if report_months:
            cadences.append(("report", int(report_months)))
        if not cadences:
            return []

        horizon_days = max(0, int(horizon_years)) * 365
        for kind, months in cadences:
            if months <= 0:
                continue
            sequence = 1
            while True:
                offset_days = int(round(months * 30.44 * sequence))
                if offset_days > horizon_days:
                    break
                due = start + datetime.timedelta(days=offset_days)
                out.append({
                    "matter": filing.get("matter"),
                    "filing_id": filing.get("id"),
                    "kind": kind,
                    "sequence": sequence,
                    "due_at": due.isoformat(),
                    "watch_from": (due - datetime.timedelta(days=lead_days)).isoformat(),
                })
                sequence += 1
        out.sort(key=lambda e: e["due_at"])
    except Exception:
        return []
    return out


# ── Part 7a: the initiative as the merge unit ───────────────────────────────────────────────

def initiative_of(slug):
    """The initiative a branch slug belongs to.

    Slugs are generated as `<initiative>-<slice|group>-<n>` by planner.py, so the initiative is
    recoverable from the name alone — no extra table, no migration, and it works retroactively
    on branches that already exist. Returns "" when the slug carries no initiative.
    """
    try:
        text = str(slug or "").strip().lower()
        if not text:
            return ""
        # Strip the trailing shard suffix, however many are stacked. `contracts` is included
        # because planner.py emits it as the FIRST task of every initiative — it is the shard
        # every sibling depends on, so grouping it separately would split exactly the changeset
        # this function exists to keep together.
        pattern = re.compile(r"-(?:slice|group|part|shard|attempt|contracts)-?\d*$")
        while True:
            stripped = pattern.sub("", text)
            if stripped == text:
                break
            text = stripped
        return text
    except Exception:
        return ""


def group_into_initiatives(branches):
    """Collapse branch-level merge candidates into initiative-level cards.

    Returns {initiative: {"branches": [...], "ready": bool, "blocked_by": [...]}}. An initiative
    is READY only when every one of its branches is — one card judging a coherent changeset,
    rather than N cards each judging a fragment that does not make sense alone. That is the
    Part 7 claim ("thousands of merge decisions collapse to dozens") stated as a function.

    `branches` are dicts: {"slug", "ready": bool, "blocked_by": [...]}. Never raises.
    """
    out = {}
    try:
        for branch in branches or ():
            if not isinstance(branch, dict):
                continue
            slug = branch.get("slug")
            if not slug:
                continue
            key = initiative_of(slug) or str(slug)
            bucket = out.setdefault(key, {"branches": [], "ready": True, "blocked_by": []})
            bucket["branches"].append(slug)
            if branch.get("ready") is not True:
                bucket["ready"] = False
                bucket["blocked_by"].append(slug)
            for blocker in branch.get("blocked_by") or ():
                if blocker not in bucket["blocked_by"]:
                    bucket["blocked_by"].append(blocker)
        for bucket in out.values():
            bucket["branches"].sort()
    except Exception:
        return {}
    return out


def collapse_ratio(branches):
    """Merge decisions before vs after grouping. 1.0 means grouping bought nothing."""
    try:
        total = len([b for b in (branches or ()) if isinstance(b, dict) and b.get("slug")])
        if not total:
            return None
        return round(len(group_into_initiatives(branches)) / total, 4)
    except Exception:
        return None


# ── Part 7b: disposition memory ─────────────────────────────────────────────────────────────

#: Closure reasons that mean the work should never have been GENERATED.
WASTEFUL_DISPOSITIONS = ("duplicate", "superseded", "already-done", "no-op", "obsolete")


def disposition_signal(closures, min_occurrences=2):
    """What the planner should stop generating, learned from how branches closed.

    `closures` are dicts: {"slug", "disposition", "initiative"?}. Returns
    {"suppress": [...], "by_initiative": {...}, "wasted": int, "total": int, "waste_ratio": float}.

    The point is the direction of the arrow. Closing a duplicate is cheap and teaches nothing;
    the compounding win is that the same duplicate is never generated again. An initiative that
    keeps producing duplicates gets suppressed by NAME, because the pattern is in the planner's
    decomposition, not in any one shard.

    `min_occurrences` guards against suppressing a whole initiative on one bad shard.
    Never raises.
    """
    result = {"suppress": [], "by_initiative": {}, "wasted": 0, "total": 0, "waste_ratio": None}
    try:
        counts = {}
        for closure in closures or ():
            if not isinstance(closure, dict):
                continue
            slug = closure.get("slug")
            if not slug:
                continue
            result["total"] += 1
            disposition = str(closure.get("disposition") or "").lower()
            if disposition not in WASTEFUL_DISPOSITIONS:
                continue
            result["wasted"] += 1
            initiative = closure.get("initiative") or initiative_of(slug) or str(slug)
            bucket = counts.setdefault(initiative, {"count": 0, "reasons": {}, "slugs": []})
            bucket["count"] += 1
            bucket["reasons"][disposition] = bucket["reasons"].get(disposition, 0) + 1
            bucket["slugs"].append(slug)

        for initiative, bucket in counts.items():
            bucket["slugs"].sort()
            result["by_initiative"][initiative] = bucket
            if bucket["count"] >= min_occurrences:
                result["suppress"].append(initiative)
        result["suppress"].sort()
        if result["total"]:
            result["waste_ratio"] = round(result["wasted"] / result["total"], 4)
    except Exception:
        pass
    return result


def should_generate(candidate_slug, signal, min_occurrences=2):
    """Ask disposition memory whether this work is worth generating at all.

    Returns (bool, reason). This is the read side of the loop — the planner calls it BEFORE
    decomposing, which is the only place the saving can actually be taken. Never raises.
    """
    try:
        initiative = initiative_of(candidate_slug) or str(candidate_slug or "")
        if not initiative:
            return True, ""
        bucket = (signal or {}).get("by_initiative", {}).get(initiative)
        if not bucket or bucket.get("count", 0) < min_occurrences:
            return True, ""
        reasons = ", ".join(f"{k}x{v}" for k, v in sorted(bucket.get("reasons", {}).items()))
        return False, (f"'{initiative}' has closed {bucket['count']} branches as wasted "
                       f"({reasons}) — generating another repeats work the fleet already "
                       f"decided was not worth doing")
    except Exception:
        return True, ""


def render(report):
    """Operator summary for whichever report is passed. Never raises."""
    try:
        if not isinstance(report, dict):
            return "nothing to report"
        if "hedgeable_ratio" in report:
            ratio = report.get("hedgeable_ratio")
            lines = ["EXPOSURE-TO-HEDGE FLYWHEEL",
                     f"  quantified   ${report.get('quantified_usd', 0):,.2f}",
                     f"  hedgeable    ${report.get('hedgeable_usd', 0):,.2f}"
                     + (f"  ({ratio:.0%})" if ratio is not None else ""),
                     f"  unhedgeable  ${report.get('unhedgeable_usd', 0):,.2f}"]
            backlog = report.get("foundry_backlog") or []
            if backlog:
                lines.append("  instrument-foundry backlog (largest first):")
                for item in backlog[:5]:
                    lines.append(f"    ${item['expected_loss_usd']:,.2f}  {item['id']}"
                                 f"  — {item['reason']}")
            return "\n".join(lines)
        if "suppress" in report:
            lines = ["DISPOSITION MEMORY",
                     f"  {report.get('wasted', 0)}/{report.get('total', 0)} closures were wasted"]
            for initiative in report.get("suppress", []):
                bucket = report["by_initiative"][initiative]
                lines.append(f"  SUPPRESS {initiative} ({bucket['count']} wasted)")
            return "\n".join(lines)
        return "nothing to report"
    except Exception:
        return "report unavailable"
