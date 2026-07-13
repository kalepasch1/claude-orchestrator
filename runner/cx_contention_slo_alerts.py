#!/usr/bin/env python3
"""
cx_contention_slo_alerts.py - Contention SLO alerts for systemic low-consensus domains.

Aggregates recent determinations by expert domain and opens an inbox alert
(kind='contention_slo') when any domain's average consensus stays below a floor
(default 0.6, referencing owner_model consensus_floor) across N>=3 determinations.
Surfaces systemic uncertainty in a domain early rather than letting it compound silently.

Read-only except the alert digest; no schema change; does not edit committees.py.
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Minimum determinations in a domain before we consider it for alerting
MIN_DETERMINATIONS = 3
# Default contention floor — domains averaging below this trigger an alert
DEFAULT_CONTENTION_FLOOR = 0.6
# How far back to look (days)
LOOKBACK_DAYS = int(os.environ.get("ORCH_CONTENTION_LOOKBACK_DAYS", "30") or 30)


def _contention_floor():
    """Contention floor: use owner_model consensus_floor if available, else default 0.6."""
    try:
        r = db.select("owner_model", {"select": "value", "key": "eq.consensus_floor"}) or []
        if r:
            # Use a lower threshold than the consensus floor itself — we alert on
            # domains consistently *well below* the normal bar
            return min(float(r[0]["value"]) * 0.7, DEFAULT_CONTENTION_FLOOR)
    except Exception:
        pass
    return DEFAULT_CONTENTION_FLOOR


def _recent_determinations():
    """Fetch recent determinations with consensus data."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    try:
        return db.select("determinations", {
            "select": "id,subject_type,title,consensus_pct,contributors,factions,created_at",
            "created_at": f"gte.{cutoff}",
            "order": "created_at.desc",
            "limit": "200",
        }) or []
    except Exception:
        return []


def _extract_domains(det):
    """Extract expert domains from a determination's contributors."""
    domains = set()
    contributors = det.get("contributors")
    if isinstance(contributors, str):
        try:
            contributors = json.loads(contributors)
        except Exception:
            contributors = []
    if not isinstance(contributors, list):
        return domains
    for c in contributors:
        expert = c.get("expert") or c.get("chair") or ""
        if expert:
            # Domain is the expert/committee name (e.g. 'legal', 'technical', 'financial')
            domains.add(expert.lower().strip())
    # Also use subject_type as a domain signal
    st = (det.get("subject_type") or "").lower().strip()
    if st:
        domains.add(st)
    return domains


def _aggregate_by_domain(dets):
    """Group determinations by domain and compute average consensus."""
    domain_data = {}  # domain -> list of consensus_pct values
    for det in dets:
        cpct = det.get("consensus_pct")
        if cpct is None:
            continue
        cpct = float(cpct)
        domains = _extract_domains(det)
        for d in domains:
            if d not in domain_data:
                domain_data[d] = []
            domain_data[d].append({"consensus_pct": cpct,
                                   "title": (det.get("title") or "")[:100],
                                   "id": det.get("id")})
    return domain_data


def _already_alerted(domain):
    """Check if we already sent a contention_slo alert for this domain recently."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=7)).isoformat()
    try:
        rows = db.select("inbox", {
            "select": "id",
            "kind": "eq.contention_slo",
            "created_at": f"gte.{cutoff}",
            "title": f"like.*{domain[:50]}*",
            "limit": "1",
        }) or []
        return len(rows) > 0
    except Exception:
        return False


def run():
    """Main entry point: scan recent determinations for domains with systemic low consensus."""
    floor = _contention_floor()
    dets = _recent_determinations()
    if not dets:
        return {"status": "ok", "alerts": 0, "note": "no recent determinations"}

    domain_data = _aggregate_by_domain(dets)
    alerts = []

    for domain, entries in domain_data.items():
        if len(entries) < MIN_DETERMINATIONS:
            continue
        avg_consensus = sum(e["consensus_pct"] for e in entries) / len(entries)
        if avg_consensus >= floor:
            continue
        if _already_alerted(domain):
            continue

        titles = [e["title"] for e in entries[:5]]
        body = (f"Domain '{domain}' has averaged {round(avg_consensus * 100, 1)}% consensus "
                f"across {len(entries)} determinations in the last {LOOKBACK_DAYS} days "
                f"(floor: {round(floor * 100, 1)}%). "
                f"Recent determinations: {'; '.join(t for t in titles if t)}")

        try:
            db.insert("inbox", {
                "kind": "contention_slo",
                "title": f"Contention SLO: domain '{domain}' at {round(avg_consensus * 100)}% avg consensus",
                "body": body[:3000],
                "meta": json.dumps({
                    "domain": domain,
                    "avg_consensus": round(avg_consensus, 3),
                    "count": len(entries),
                    "floor": floor,
                    "determination_ids": [e.get("id") for e in entries[:10]],
                }),
            })
            alerts.append({"domain": domain, "avg_consensus": round(avg_consensus, 3),
                           "count": len(entries)})
        except Exception:
            pass

    return {"status": "ok", "alerts": len(alerts), "details": alerts}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
