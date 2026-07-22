#!/usr/bin/env python3
"""
cx_evidence_freshness.py - review recent determinations for stale grounding.

Scores each recent committee determination by the freshness of the portfolio signals
that grounded it:
  - app_revenue / app_revenue_history for revenue and usage context
  - integrated outcomes as the recent merge signal
  - whether the optional live external-evidence layer could have supplied reality
    checks for legal/pricing/privacy/competitive decisions

The job is read-only over source evidence and writes only a pending owner-review card
for stale candidates (approvals.kind='stale_evidence'). No schema changes.
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import committees


RECENT_LIMIT = int(os.environ.get("CX_EVIDENCE_FRESHNESS_LIMIT", "120"))
STALE_SCORE = float(os.environ.get("CX_EVIDENCE_STALE_SCORE", "60"))
STALE_AFTER_DAYS = float(os.environ.get("CX_EVIDENCE_STALE_AFTER_DAYS", "21"))
REVIEW_LIMIT = int(os.environ.get("CX_EVIDENCE_REVIEW_LIMIT", "12"))

REALITY_SENSITIVE = (
    "legal", "compliance", "regulat", "privacy", "pricing", "competitive",
    "market", "partnership", "claim", "terms", "fee", "data use", "gdpr",
    "ccpa", "licens", "security", "policy",
)


def _safe_select(table, params=None):
    try:
        return db.select(table, params or {"select": "*"}) or []
    except Exception:
        return []


def _safe_insert(table, row):
    try:
        return db.insert(table, row)
    except Exception as e:
        print(f"cx_evidence_freshness: failed to insert {table}: {e}")
        return None


def _parse_ts(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, datetime.timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.lower() == "now()":
        return datetime.datetime.now(datetime.timezone.utc)
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


def _days_between(later, earlier):
    if not later or not earlier:
        return None
    return max(0.0, (later - earlier).total_seconds() / 86400.0)


def _signal_ts(row):
    for key in ("captured_at", "updated_at", "created_at", "decided_at"):
        ts = _parse_ts((row or {}).get(key))
        if ts:
            return ts
    return None


def _determination_text(det):
    parts = [det.get("title"), det.get("body"), det.get("recommendation"),
             det.get("position"), det.get("onepager")]
    cert = det.get("certificate")
    if isinstance(cert, dict):
        parts.append(json.dumps(cert, default=str))
    return " ".join(str(p or "") for p in parts)


def _app_for(det, apps):
    text = _determination_text(det).lower()
    subject_id = str(det.get("subject_id") or "")
    if det.get("app"):
        return det.get("app")
    for app in apps:
        name = (app.get("app") or app.get("name") or "").lower()
        if name and name in text:
            return app.get("app") or app.get("name")

    # Decision determinations often point back to an approval whose project is the app.
    if subject_id:
        rows = _safe_select("approvals", {"select": "project", "id": f"eq.{subject_id}", "limit": "1"})
        if rows and rows[0].get("project"):
            return rows[0]["project"]
    return None


def _latest_before(rows, cutoff):
    best = None
    best_ts = None
    for row in rows:
        ts = _signal_ts(row)
        if not ts or (cutoff and ts > cutoff):
            continue
        if best_ts is None or ts > best_ts:
            best, best_ts = row, ts
    return best, best_ts


def _revenue_age(app, decided_at):
    if not app:
        return None, "no app match"
    hist = _safe_select("app_revenue_history", {
        "select": "app,mrr_usd,active_users,captured_at,created_at",
        "app": f"eq.{app}",
        "order": "captured_at.desc",
        "limit": "120",
    })
    row, ts = _latest_before(hist, decided_at)
    if row and ts:
        return _days_between(decided_at, ts), f"app_revenue_history:{ts.date().isoformat()}"

    current = _safe_select("app_revenue", {"select": "*", "app": f"eq.{app}", "limit": "1"})
    if current:
        ts = _signal_ts(current[0])
        if ts and (not decided_at or ts <= decided_at):
            return _days_between(decided_at, ts), f"app_revenue:{ts.date().isoformat()}"
        return None, "app_revenue:no timestamp"
    return None, "no app_revenue"


def _merge_age(app, decided_at):
    if not app:
        return None, "no app match"
    rows = _safe_select("outcomes", {
        "select": "project,slug,integrated,created_at",
        "project": f"eq.{app}",
        "integrated": "eq.true",
        "order": "created_at.desc",
        "limit": "120",
    })
    row, ts = _latest_before(rows, decided_at)
    if row and ts:
        return _days_between(decided_at, ts), f"outcomes:{row.get('slug') or '?'}@{ts.date().isoformat()}"
    return None, "no integrated merge before decision"


def _age_score(age_days):
    if age_days is None:
        return 35.0
    if age_days <= 2:
        return 100.0
    if age_days <= 7:
        return 85.0
    if age_days <= 14:
        return 70.0
    if age_days <= 30:
        return 45.0
    return 20.0


def _needs_external(det):
    text = _determination_text(det).lower()
    return any(k in text for k in REALITY_SENSITIVE)


def _external_available(det):
    if not _needs_external(det):
        return True, "not reality-sensitive"
    title = det.get("title") or ""
    body = det.get("body") or det.get("onepager") or ""
    committees_to_probe = ("Legal & Compliance", "Pricing & Monetization",
                           "Competitive Strategy", "Data & Privacy")
    for name in committees_to_probe:
        try:
            if committees._external_evidence(name, title, body):
                return True, name
        except Exception:
            continue
    return False, "no external evidence returned"


def _score(det, apps):
    decided_at = (_parse_ts(det.get("created_at")) or _parse_ts(det.get("decided_at")) or
                  datetime.datetime.now(datetime.timezone.utc))
    app = _app_for(det, apps)
    rev_age, rev_source = _revenue_age(app, decided_at)
    merge_age, merge_source = _merge_age(app, decided_at)
    ext_ok, ext_source = _external_available(det)

    ages = [a for a in (rev_age, merge_age) if a is not None]
    max_age = max(ages) if ages else None
    freshness = (_age_score(rev_age) + _age_score(merge_age)) / 2.0
    if _needs_external(det) and not ext_ok:
        freshness = min(freshness - 25.0, 55.0)
    score = max(0.0, min(100.0, freshness))

    reasons = []
    if rev_age is None:
        reasons.append(f"revenue signal missing ({rev_source})")
    elif rev_age > STALE_AFTER_DAYS:
        reasons.append(f"revenue signal {rev_age:.1f}d old ({rev_source})")
    if merge_age is None:
        reasons.append(f"merge signal missing ({merge_source})")
    elif merge_age > STALE_AFTER_DAYS:
        reasons.append(f"merge signal {merge_age:.1f}d old ({merge_source})")
    if _needs_external(det) and not ext_ok:
        reasons.append("external evidence unavailable for a reality-sensitive decision")
    if score < STALE_SCORE and not reasons:
        reasons.append("combined evidence freshness below threshold")

    return {
        "determination_id": det.get("id"),
        "subject_id": det.get("subject_id"),
        "title": det.get("title"),
        "app": app or "ORCHESTRATOR",
        "decided_at": decided_at.isoformat(),
        "score": round(score, 1),
        "max_age_days": round(max_age, 1) if max_age is not None else None,
        "revenue_age_days": round(rev_age, 1) if rev_age is not None else None,
        "merge_age_days": round(merge_age, 1) if merge_age is not None else None,
        "revenue_source": rev_source,
        "merge_source": merge_source,
        "external_evidence_available": ext_ok,
        "external_evidence_source": ext_source,
        "stale": bool(score < STALE_SCORE or any(a is not None and a > STALE_AFTER_DAYS for a in ages)
                      or (_needs_external(det) and not ext_ok)),
        "reasons": reasons,
    }


def _existing_stale_keys():
    rows = _safe_select("approvals", {
        "select": "title,detail,status,kind",
        "kind": "eq.stale_evidence",
        "status": "eq.pending",
        "limit": "500",
    })
    blob = "\n".join(f"{r.get('title') or ''}\n{r.get('detail') or ''}" for r in rows)
    return set(re.findall(r"determination_id[=:]\s*([^\s,}\]]+)", blob))


def _file_review(score):
    det_id = str(score.get("determination_id") or "")
    title = f"Re-review stale evidence: {(score.get('title') or 'untitled determination')[:120]}"
    why = "; ".join(score.get("reasons") or ["evidence freshness score below threshold"])
    detail = json.dumps(score, indent=2, default=str)
    return _safe_insert("approvals", {
        "project": score.get("app") or "ORCHESTRATOR",
        "kind": "stale_evidence",
        "title": title,
        "why": f"Determination {det_id} scored {score['score']}/100 for evidence freshness: {why}.",
        "value": "Re-review decisions that may have been made on stale revenue, merge, or external evidence.",
        "risk": "Low - review card only; no app data or schema changes.",
        "detail": f"determination_id={det_id}\n{detail}",
        "command": "",
    })


def run():
    dets = _safe_select("determinations", {
        "select": "*",
        "order": "created_at.desc",
        "limit": str(RECENT_LIMIT),
    })
    apps = _safe_select("app_revenue", {"select": "*"}) + _safe_select("projects", {"select": "name"})
    existing = _existing_stale_keys()

    scored = [_score(d, apps) for d in dets]
    stale = [s for s in scored if s["stale"]]
    stale.sort(key=lambda s: (s["score"], -(s.get("max_age_days") or 0)))

    filed = 0
    for s in stale[:REVIEW_LIMIT]:
        det_id = str(s.get("determination_id") or "")
        if det_id and det_id in existing:
            continue
        if _file_review(s):
            filed += 1
            existing.add(det_id)

    avg = round(sum(s["score"] for s in scored) / len(scored), 1) if scored else None
    print(f"cx_evidence_freshness: scored {len(scored)} determinations, "
          f"{len(stale)} stale candidates, filed {filed} review card(s)"
          + (f", avg freshness {avg}/100" if avg is not None else ""))
    return {"scored": len(scored), "stale": len(stale), "filed": filed, "avg_score": avg}


if __name__ == "__main__":
    run()
