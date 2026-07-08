#!/usr/bin/env python3
"""Conservative queue bankruptcy cleanup.

This job keeps the backlog honest without spending model tokens:

* collapse obvious duplicate queued rows by normalized intent fingerprint;
* quarantine stale generic queued work that has not moved in many days;
* close recovery rows when the original task is already DONE/MERGED;
* write a compact heartbeat for dashboards/autopilot.

It is intentionally bounded and fail-soft. Protected work such as release fixes,
recovery tasks, canaries, and improve-* tasks is not stale-quarantined unless a
specific proof says the row is already resolved.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MARK = "queue-bankruptcy"
LIMIT = int(os.environ.get("ORCH_QUEUE_BANKRUPTCY_LIMIT", "1000"))
STALE_DAYS = float(os.environ.get("ORCH_TASK_BANKRUPTCY_DAYS", "21"))
DEDUP_MIN_LEN = int(os.environ.get("ORCH_QUEUE_BANKRUPTCY_DEDUP_MIN_LEN", "80"))
STALE_ENABLED = os.environ.get("ORCH_QUEUE_BANKRUPTCY_STALE", "true").lower() in ("1", "true", "yes", "on")

PROTECTED_PREFIXES = (
    "recover-missing-branch-",
    "rework-",
    "canary-",
    "improve-",
    "relfix-",
    "qafix-",
    "buildfix-",
    "deployfix-",
    "copyfix-",
)
LOW_VALUE_PREFIXES = ("cont-", "batch-mech-", "backlog-batch-")
STOPWORDS = set(
    "the a an and or of to in for with by from on at into this that these those is are was were "
    "be been being add update fix make create implement improve review code app project task prompt".split()
)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_ts(value):
    if not value:
        return None
    raw = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed
    except Exception:
        return None


def _age_days(value):
    ts = _parse_ts(value)
    if not ts:
        return 0.0
    return max(0.0, (_now() - ts).total_seconds() / 86400.0)


def _original(text):
    try:
        import pipeline_contract
        return pipeline_contract.original_request(text or "")
    except Exception:
        return text or ""


def _tokens(text):
    return [
        w for w in re.findall(r"[a-z0-9]+", _original(text).lower())
        if len(w) > 3 and w not in STOPWORDS
    ]


def _fingerprint(row):
    toks = _tokens(row.get("prompt") or row.get("note") or row.get("slug") or "")
    if len(" ".join(toks)) < DEDUP_MIN_LEN:
        return ""
    stem = " ".join(sorted(set(toks))[:80])
    raw = f"{row.get('project_id') or ''}|{stem}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _slug(row):
    return str((row or {}).get("slug") or "")


def _protected(row):
    slug = _slug(row)
    note = str((row or {}).get("note") or "").lower()
    return slug.startswith(PROTECTED_PREFIXES) or "release_train" in note or "vercel" in note


def _generic_stale(row):
    if _protected(row):
        return False
    if row.get("material") or (row.get("deps") or []):
        return False
    slug = _slug(row)
    if slug.startswith(LOW_VALUE_PREFIXES):
        return True
    prompt = _original(row.get("prompt") or "")
    return len(prompt) < 180 and _age_days(row.get("updated_at") or row.get("created_at")) >= STALE_DAYS * 2


def _select_queued(limit):
    variants = [
        "id,slug,prompt,note,state,project_id,created_at,updated_at,material,deps",
        "id,slug,prompt,note,state,project_id,created_at,updated_at",
        "*",
    ]
    last = None
    for select_cols in variants:
        try:
            return db.select("tasks", {"select": select_cols, "state": "eq.QUEUED",
                                       "order": "updated_at.asc", "limit": str(limit)}) or []
        except Exception as e:
            last = e
    raise last


def _recovery_root(slug):
    prefix = "recover-missing-branch-"
    s = str(slug or "")
    while s.startswith(prefix):
        s = s[len(prefix):]
    return s


def _resolved_recovery(row):
    slug = _slug(row)
    if not slug.startswith("recover-missing-branch-"):
        return False
    root = _recovery_root(slug)
    if not root:
        return False
    try:
        rows = db.select("tasks", {"select": "id,state,slug", "project_id": f"eq.{row.get('project_id')}",
                                   "slug": f"eq.{root}", "state": "in.(DONE,MERGED)",
                                   "limit": "1"}) or []
        return bool(rows)
    except Exception:
        return False


def _patch(row, patch, dry_run=False):
    if dry_run:
        return True
    try:
        db.update("tasks", {"id": row["id"]}, patch)
        return True
    except Exception as e:
        print(f"{MARK}: update failed for {_slug(row)}: {e}")
        return False


def _dedupe(rows, dry_run=False):
    groups = {}
    for row in rows:
        if _protected(row) or row.get("material") or (row.get("deps") or []):
            continue
        fp = _fingerprint(row)
        if fp:
            groups.setdefault(fp, []).append(row)
    duplicate_groups = duplicates = 0
    for fp, group in groups.items():
        if len(group) <= 1:
            continue
        duplicate_groups += 1
        group.sort(key=lambda r: r.get("created_at") or r.get("updated_at") or "")
        keeper = group[0]
        for dup in group[1:]:
            if _patch(dup, {"state": "QUARANTINED",
                            "account": None,
                            "updated_at": "now()",
                            "note": f"{MARK}: duplicate of {keeper.get('slug')} (fp={fp}); recoverable if needed"},
                      dry_run=dry_run):
                duplicates += 1
    return {"duplicate_groups": duplicate_groups, "quarantined": duplicates}


def _resolve_recoveries(rows, dry_run=False):
    closed = 0
    for row in rows:
        if not _resolved_recovery(row):
            continue
        if _patch(row, {"state": "QUARANTINED",
                        "account": None,
                        "updated_at": "now()",
                        "note": f"{MARK}: original task {_recovery_root(_slug(row))} is already DONE/MERGED"},
                  dry_run=dry_run):
            closed += 1
    return closed


def _quarantine_stale(rows, dry_run=False):
    if not STALE_ENABLED:
        return 0
    stale = 0
    for row in rows:
        age = _age_days(row.get("updated_at") or row.get("created_at"))
        if age < STALE_DAYS or not _generic_stale(row):
            continue
        if _patch(row, {"state": "QUARANTINED",
                        "account": None,
                        "updated_at": "now()",
                        "note": f"{MARK}: stale low-value queued row ({age:.1f}d); regenerate from current intent if still needed"},
                  dry_run=dry_run):
            stale += 1
    return stale


def run(limit=LIMIT, dry_run=False):
    rows = _select_queued(limit)
    dedup = _dedupe(rows, dry_run=dry_run)
    resolved_recovery = _resolve_recoveries(rows, dry_run=dry_run)
    stale = _quarantine_stale(rows, dry_run=dry_run)

    try:
        import task_dedup
        protected_released = task_dedup.release_protected() if not dry_run else 0
    except Exception:
        protected_released = 0

    summary = {
        "scanned": len(rows),
        "dry_run": dry_run,
        "dedup": dedup,
        "resolved_recovery_quarantined": resolved_recovery,
        "stale_quarantined": stale,
        "protected_released": protected_released,
        "stale_days": STALE_DAYS,
    }
    if not dry_run:
        try:
            db.insert("controls", {"key": MARK, "value": json.dumps(summary, default=str),
                                   "updated_at": "now()"}, upsert=True)
        except Exception:
            pass
    print(f"{MARK}: {summary}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=LIMIT)
    args = parser.parse_args()
    print(json.dumps(run(limit=args.limit, dry_run=args.dry_run), indent=2, default=str))
