#!/usr/bin/env python3
"""
cx_reviewer_trust_tile.py - Trust report digest for owner inbox.

Summarizes committee_scoreboard (accuracy + Brier by expert domain) plus the count
of dissent_vindicated determinations into a concise inbox digest (kind='trust_report').
Sort by accuracy; call out the worst-calibrated (highest Brier) domains.
Read-only except the digest; no schema change; does not edit committees.py.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def run():
    """Generate a trust_report inbox item summarizing calibration and dissent vindication."""
    sb = db.select("committee_scoreboard", {
        "select": "committee,accuracy,brier,calls",
        "entity_type": "eq.committee",
        "order": "accuracy.desc",
    }) or []

    vindicated = db.select("determinations", {
        "select": "id",
        "dissent_vindicated": "eq.true",
    }) or []
    vindicated_count = len(vindicated)

    if not sb and vindicated_count == 0:
        return {"skipped": True, "reason": "no scoreboard data or vindicated dissents"}

    lines = []
    worst_brier_domain = None
    worst_brier_val = -1.0

    for row in sb:
        domain = row.get("committee") or "unknown"
        acc = row.get("accuracy")
        brier = row.get("brier")
        calls = row.get("calls") or 0
        acc_str = f"{acc:.1%}" if acc is not None else "n/a"
        brier_str = f"{brier:.3f}" if brier is not None else "n/a"
        lines.append(f"  {domain}: accuracy {acc_str}, Brier {brier_str} ({calls} calls)")
        if brier is not None and brier > worst_brier_val:
            worst_brier_val = brier
            worst_brier_domain = domain

    body = "Committee calibration (sorted by accuracy):\n" + "\n".join(lines)

    if worst_brier_domain and worst_brier_val > 0:
        body += f"\n\nWorst-calibrated domain: {worst_brier_domain} (Brier {worst_brier_val:.3f})"

    body += f"\n\nDissent-vindicated determinations: {vindicated_count}"

    db.insert("inbox", {
        "kind": "trust_report",
        "title": "Reviewer trust & calibration report",
        "body": body,
    })

    return {"created": True, "domains": len(sb), "vindicated": vindicated_count}


if __name__ == "__main__":
    print(run())
