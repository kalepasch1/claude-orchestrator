#!/usr/bin/env python3
"""
cx_shadow_cade.py - SHADOW MODE for CADE: free ground truth before granting more autonomy.

Every approval the owner decides by hand is a labelled example the committee stack never
sees. This module replays a bounded handful of those already-decided approvals through
`committees.review()` in SHADOW (no execution, no approval mutation) and records where the
machine's recommendation diverged from the human's call.

Why it exists: seat calibration, the portfolio bandit and the autonomy ramp all learn from
`outcome` labels. Waiting for post-ship revenue signal is slow; a human approve/deny is an
immediate, high-quality label that costs nothing extra to collect. Divergences are the
accuracy signal that should gate any future autonomy grant.

Writes (and only writes):
  - determination_outcomes rows with source='shadow'
  - one inbox digest row summarising the divergences found in this run
  - determination_outcomes.csv at the repo root: a local, append-safe audit trail so the
    shadow record is inspectable without DB access

Everything else is read-only. `committees.py` is reused as-is and never edited.

Usage:
    python3 runner/cx_shadow_cade.py [--limit 5] [--csv PATH] [--dry-run]
"""
import csv
import os
import sys
from argparse import ArgumentParser
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Bounded by default: shadow review costs real model calls, so a run is deliberately small.
DEFAULT_LIMIT = int(os.environ.get("ORCH_SHADOW_CADE_LIMIT", "5"))
CSV_PATH = os.environ.get(
    "ORCH_SHADOW_CADE_CSV",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "determination_outcomes.csv"),
)
CSV_FIELDS = ["ts", "source", "approval_id", "subject_type", "human_decision",
              "cade_recommendation", "cade_stance", "diverged", "consensus_pct", "title"]

# Human decisions we can turn into a label. Anything else (pending, expired) is skipped.
HUMAN_APPROVED = ("approved",)
HUMAN_DENIED = ("denied", "rejected")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _cade_stance(recommendation):
    """Collapse a CADE recommendation string to approve / deny so it is comparable to a human call.

    Returns None when the panel declined to take a side (needs-info); those are not divergences.
    """
    rec = (recommendation or "").strip().upper()
    if not rec:
        return None
    if rec.startswith("GO"):
        return "approved"
    if rec.startswith(("HOLD", "NO-GO", "NOGO", "STOP", "BLOCK")):
        return "denied"
    if rec.startswith("ESCALATE"):
        return None          # explicitly punting to a human is not a disagreement with one
    return None


def _human_stance(status):
    s = (status or "").strip().lower()
    if s in HUMAN_APPROVED:
        return "approved"
    if s in HUMAN_DENIED:
        return "denied"
    return None


def recent_decided_approvals(limit):
    """Recently human-decided approvals, newest first. Fail-soft: [] when the DB is unreachable."""
    try:
        rows = db.select("approvals", {
            "select": "id,project,kind,title,why,status,updated_at",
            "status": f"in.({','.join(HUMAN_APPROVED + HUMAN_DENIED)})",
            "order": "updated_at.desc",
            "limit": str(max(1, int(limit)) * 4),
        }) or []
    except Exception as e:
        print(f"cx_shadow_cade: approvals read failed ({e}); fail-soft empty")
        return []
    return [r for r in rows if _human_stance(r.get("status"))]


def _already_shadowed():
    """Approval ids that already have a shadow row, so a rerun does not double-count."""
    try:
        rows = db.select("determination_outcomes", {"select": "subject_id", "source": "eq.shadow"}) or []
    except Exception:
        return set()
    return {r.get("subject_id") for r in rows if r.get("subject_id")}


def shadow_review(approval):
    """Run committees.review() in shadow on one approval. Returns the review dict, or None."""
    import committees                      # imported lazily: keeps py_compile/import cheap
    title = approval.get("title") or f"approval {approval.get('id')}"
    body = approval.get("why") or ""
    try:
        return committees.review("shadow_approval", approval.get("id"), title, body,
                                 app=approval.get("project"))
    except Exception as e:
        print(f"cx_shadow_cade: shadow review failed for {approval.get('id')} ({e}); fail-soft skip")
        return None


def _record(approval, review, dry_run=False):
    """Build the shadow record and persist it (determination_outcomes + CSV). Returns the record."""
    human = _human_stance(approval.get("status"))
    cade = _cade_stance((review or {}).get("recommendation"))
    diverged = bool(cade and human and cade != human)
    rec = {
        "ts": _now(),
        "source": "shadow",
        "approval_id": approval.get("id"),
        "subject_type": "shadow_approval",
        "human_decision": human,
        "cade_recommendation": (review or {}).get("recommendation") or "",
        "cade_stance": cade or "abstain",
        "diverged": diverged,
        "consensus_pct": (review or {}).get("consensus_pct"),
        "title": (approval.get("title") or "")[:200],
    }
    if dry_run:
        return rec
    try:
        db.insert("determination_outcomes", {
            "subject_id": approval.get("id"),
            "metric": "human_agreement",
            # +1 when the machine matched the human, -1 when it did not, 0 when it abstained.
            "labeled_outcome": 0.0 if not cade else (-1.0 if diverged else 1.0),
            "source": "shadow",
        })
    except Exception as e:
        print(f"cx_shadow_cade: shadow row insert failed ({e}); CSV trail still written")
    return rec


def write_csv(records, path=CSV_PATH):
    """Append shadow records to the local audit CSV, writing the header on first creation."""
    if not records:
        return path
    try:
        exists = os.path.isfile(path) and os.path.getsize(path) > 0
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
            if not exists:
                w.writeheader()
            for r in records:
                w.writerow(r)
    except Exception as e:
        print(f"cx_shadow_cade: CSV write failed ({e}); fail-soft continue")
    return path


def _digest(records):
    """One inbox row per run summarising divergences. Silent when nothing diverged."""
    diverged = [r for r in records if r.get("diverged")]
    if not diverged:
        return 0
    lines = [f"- {r['title']}: you {r['human_decision']}, CADE said {r['cade_recommendation']}"
             for r in diverged[:10]]
    try:
        db.insert("inbox", {
            "kind": "shadow_cade_divergence",
            "title": f"Shadow CADE disagreed with you on {len(diverged)} of {len(records)} decisions",
            "body": "Replayed your recent approvals through the committee stack without acting on them.\n"
                    + "\n".join(lines)
                    + "\n\nThese are the accuracy gaps to close before widening autonomy.",
            "status": "unread",
        })
    except Exception as e:
        print(f"cx_shadow_cade: digest insert failed ({e}); fail-soft continue")
        return 0
    return len(diverged)


def run(limit=DEFAULT_LIMIT, csv_path=CSV_PATH, dry_run=False):
    """Shadow-review up to `limit` recently human-decided approvals. Returns the records written."""
    limit = max(1, int(limit or DEFAULT_LIMIT))
    seen = _already_shadowed()
    candidates = [a for a in recent_decided_approvals(limit) if a.get("id") not in seen][:limit]
    if not candidates:
        print("cx_shadow_cade: no un-shadowed human-decided approvals; nothing to do")
        return []
    records = []
    for a in candidates:
        review = shadow_review(a)
        if review is None:
            continue
        records.append(_record(a, review, dry_run=dry_run))
    write_csv(records, csv_path)
    n_div = 0 if dry_run else _digest(records)
    print(f"cx_shadow_cade: shadowed {len(records)} decided approvals, "
          f"{sum(1 for r in records if r.get('diverged'))} divergences ({n_div} digested) -> {csv_path}")
    return records


def main(argv=None):
    p = ArgumentParser(description="Replay human-decided approvals through CADE in shadow mode.")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="max approvals to shadow this run")
    p.add_argument("--csv", default=CSV_PATH, help="path to the shadow audit CSV")
    p.add_argument("--dry-run", action="store_true", help="compute records but write no DB rows")
    args = p.parse_args(argv)
    run(limit=args.limit, csv_path=args.csv, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
