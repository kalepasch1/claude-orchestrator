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
