#!/usr/bin/env python3
"""
cx_regret_accounting.py - for determinations with a realized negative outcome, estimate the
regret (missed upside + incurred downside) from determination_outcomes/merge_revenue and
aggregate by expert domain into an inbox report (kind='regret_report'), giving a money view
of where deliberation quality matters most. Read-only except the report; degrades gracefully
if revenue signals are missing; does not edit committees.py.
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

LIMIT = int(os.environ.get("REGRET_SCAN_LIMIT", "500"))


def _revenue_map():
    """slug -> revenue_delta from merge_revenue."""
    try:
        rows = db.select("merge_revenue", {"select": "slug,revenue_delta"}) or []
    except Exception:
        return {}
    return {r.get("slug") or "": r.get("revenue_delta") or 0.0 for r in rows}


def _outcome_map():
    """determination_id -> {outcome, label, delta} from determination_outcomes."""
    try:
        rows = db.select("determination_outcomes", {
            "select": "determination_id,outcome,label,delta",
            "limit": str(LIMIT),
        }) or []
    except Exception:
        return {}
    out = {}
    for r in rows:
        did = r.get("determination_id")
        if did:
            out[did] = r
    return out


def run():
    outcomes = _outcome_map()
    if not outcomes:
        return {"status": "no_data", "detail": "no determination_outcomes found; revenue signals may be missing"}

    dets = db.select("determinations", {
        "select": "id,title,subject,subject_id,committee,verdict,recommendation",
        "limit": str(LIMIT),
    }) or []

    if not dets:
        return {"status": "no_data", "detail": "no determinations found"}

    rev_map = _revenue_map()

    domain_regret = {}  # committee/domain -> total regret $
    detail_lines = []

    for d in dets:
        did = d.get("id")
        oc = outcomes.get(did)
        if not oc:
            continue
        outcome_val = oc.get("outcome") or 0.0
        try:
            outcome_val = float(outcome_val)
        except (ValueError, TypeError):
            outcome_val = -1.0 if str(oc.get("label", "")).lower() in ("negative", "bad", "fail") else 0.0

        if outcome_val >= 0:
            continue  # only interested in negative outcomes

        delta = 0.0
        try:
            delta = float(oc.get("delta") or 0.0)
        except (ValueError, TypeError):
            pass

        slug = d.get("subject_id") or ""
        rev_delta = rev_map.get(slug, 0.0)
        try:
            rev_delta = float(rev_delta)
        except (ValueError, TypeError):
            rev_delta = 0.0

        regret = abs(delta) + abs(min(rev_delta, 0))
        domain = d.get("committee") or "unknown"
        domain_regret[domain] = domain_regret.get(domain, 0.0) + regret

        if regret > 0:
            detail_lines.append(
                f"  {domain}: {d.get('title', '')[:60]} regret=${regret:.2f}"
            )

    if not domain_regret:
        return {"status": "ok", "detail": "no negative-outcome determinations with regret signal"}

    sorted_domains = sorted(domain_regret.items(), key=lambda x: x[1], reverse=True)
    lines = ["# Regret by Expert Domain (negative-outcome determinations)\n"]
    for domain, total in sorted_domains:
        lines.append(f"- {domain}: ${total:,.2f} total regret")
    lines.append("")
    if detail_lines:
        lines.append("## Top details")
        lines.extend(detail_lines[:20])

    body = "\n".join(lines)
    db.insert("inbox", {
        "kind": "regret_report",
        "title": "Regret accounting: where deliberation quality costs money",
        "body": body[:3000],
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    })

    return {"status": "ok", "domains": len(sorted_domains), "total_regret": sum(domain_regret.values())}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
