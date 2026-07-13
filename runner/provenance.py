#!/usr/bin/env python3
"""
provenance.py - lineage + consent for every capability. Records where a capability came
from (source app, derivation method, consent flag, data residency) so you can prove
compliance and REVOKE a capability if a source app's consent changes. instantiate() in
capability.py checks consent here before letting an app use a capability.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def record(capability_id, source_project, derivation, consent=False, residency=None):
    db.insert("capability_provenance", {"capability_id": capability_id,
              "source_project": source_project, "derivation": derivation,
              "consent": bool(consent), "data_residency": residency})


def for_capability(capability_id):
    return db.select("capability_provenance", {"select": "*", "capability_id": f"eq.{capability_id}"}) or []


def consent_ok(capability_id, target_residency=None):
    rows = for_capability(capability_id)
    if not rows:
        return False, "no provenance recorded"
    if not all(r.get("consent") for r in rows):
        return False, "a source lacks consent"
    if target_residency:
        for r in rows:
            res = r.get("data_residency")
            if res and res != target_residency:
                return False, f"residency mismatch (source {res} vs target {target_residency})"
    return True, "ok"


def revoke(capability_id):
    # flip all provenance consent off + retire the capability
    for r in for_capability(capability_id):
        db.update("capability_provenance", {"id": r["id"]}, {"consent": False})
    db.update("capabilities", {"id": capability_id}, {"status": "retired"})
    return "revoked + retired"


# ── Merge provenance ledger ──────────────────────────────────────────────────
# Ties multiple provenance records to a single merge event for batch audit/rollback.

def record_merge(merge_id, capability_ids, merge_branch="master", author=None):
    """Record a merge event linking multiple capabilities for batch audit."""
    import datetime
    entry = {
        "merge_id": merge_id,
        "capability_ids": capability_ids if isinstance(capability_ids, list) else [capability_ids],
        "merge_branch": merge_branch,
        "author": author or "",
        "merged_at": datetime.datetime.utcnow().isoformat(),
        "consent_snapshot": {},
        "status": "active",
    }
    # snapshot consent state at merge time for each capability
    for cid in entry["capability_ids"]:
        ok, reason = consent_ok(cid)
        entry["consent_snapshot"][cid] = {"ok": ok, "reason": reason}
    try:
        db.insert("merge_provenance_ledger", entry)
    except Exception:
        pass  # fail-soft: merge proceeds even if ledger write fails
    return entry


def merge_history(merge_id=None, capability_id=None, limit=100):
    """Query the merge provenance ledger. Filter by merge_id or capability_id."""
    try:
        params = {"select": "*", "order": "merged_at.desc", "limit": str(limit)}
        if merge_id:
            params["merge_id"] = f"eq.{merge_id}"
        rows = db.select("merge_provenance_ledger", params) or []
        if capability_id:
            rows = [r for r in rows if capability_id in (r.get("capability_ids") or [])]
        return rows
    except Exception:
        return []


def audit_merge(merge_id):
    """Check all capabilities in a merge still have consent. Returns (ok, violations)."""
    entries = merge_history(merge_id=merge_id)
    if not entries:
        return False, [{"error": "merge not found"}]
    violations = []
    for entry in entries:
        for cid in entry.get("capability_ids") or []:
            ok, reason = consent_ok(cid)
            if not ok:
                violations.append({"capability_id": cid, "reason": reason,
                                   "was_ok_at_merge": (entry.get("consent_snapshot") or {}).get(cid, {}).get("ok")})
    return len(violations) == 0, violations


def rollback_merge(merge_id):
    """Revoke all capabilities in a merge event and mark the merge as rolled back."""
    entries = merge_history(merge_id=merge_id)
    revoked = []
    for entry in entries:
        for cid in entry.get("capability_ids") or []:
            revoke(cid)
            revoked.append(cid)
        try:
            db.update("merge_provenance_ledger",
                      {"merge_id": entry.get("merge_id")}, {"status": "rolled_back"})
        except Exception:
            pass
    return {"merge_id": merge_id, "revoked": revoked}
