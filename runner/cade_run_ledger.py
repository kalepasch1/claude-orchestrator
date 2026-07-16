#!/usr/bin/env python3
"""
cade_run_ledger.py — Versioned serializer that captures every CADE run's moat signal.

record_run(run)      — validates and normalizes a CADE run dict into the versioned schema.
                       Deterministic output (sorted keys, consistent formatting).
                       Fail-soft on missing fields (gap markers, never raises).
validate_schema(rec) — checks a record against the current schema version.
roundtrip_check(run) — serialize then deserialize, verify equality.
persist_run(record)  — writes to Supabase cade_run_ledger table (fail-soft).
stats()              — module statistics.
"""
import os, sys, json, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SCHEMA_VERSION = "1.0"
ENABLED = os.environ.get("ORCH_CADE_LEDGER_ENABLED", "true").lower() == "true"

GAP = "__GAP__"

# ─── Schema field definitions ───

_TOP_FIELDS = [
    "schema_version",
    "recorded_at",
    "inputs",
    "weakness_ledger",
    "alignment_ledger",
    "determination",
    "credential_id",
    "roster",
    "outcome",
    "checksum",
]

_INPUT_FIELDS = ["mandate", "recipient", "facts"]

_OUTCOME_FIELDS = ["prevailed", "rfis_raised", "ruling"]

_ROSTER_ITEM_FIELDS = ["bot", "position"]


# ─── Helpers ───

def _gap(val):
    """Return the value if truthy/present, else the gap marker."""
    if val is None:
        return GAP
    return val


def _normalize_list(raw, item_fields=None):
    """Normalize a list field. Returns list of dicts with sorted keys."""
    if not isinstance(raw, list):
        return GAP
    result = []
    for item in raw:
        if isinstance(item, dict) and item_fields:
            normed = {}
            for f in sorted(item_fields):
                normed[f] = _gap(item.get(f))
            result.append(normed)
        else:
            result.append(item)
    return result


def _checksum(data):
    """Deterministic checksum of the record (excluding checksum field itself)."""
    clone = {k: v for k, v in data.items() if k != "checksum"}
    blob = json.dumps(clone, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ─── Core Functions ───

def record_run(run):
    """Validate and normalize a CADE run dict into the versioned schema.

    Deterministic output: sorted keys, consistent formatting.
    Fail-soft: missing fields get gap markers, never raises.
    """
    if not ENABLED:
        return {"schema_version": SCHEMA_VERSION, "disabled": True}

    if not isinstance(run, dict):
        run = {}

    # Inputs sub-dict
    raw_inputs = run.get("inputs") or {}
    if not isinstance(raw_inputs, dict):
        raw_inputs = {}
    inputs = {}
    for f in sorted(_INPUT_FIELDS):
        inputs[f] = _gap(raw_inputs.get(f))

    # Roster normalization
    raw_roster = run.get("roster") or run.get("bots")
    roster = _normalize_list(raw_roster, _ROSTER_ITEM_FIELDS) if isinstance(raw_roster, list) else GAP

    # Outcome sub-dict
    raw_outcome = run.get("outcome") or {}
    if not isinstance(raw_outcome, dict):
        raw_outcome = {}
    outcome = {}
    for f in sorted(_OUTCOME_FIELDS):
        outcome[f] = _gap(raw_outcome.get(f))

    record = {
        "alignment_ledger": _gap(run.get("alignment_ledger")),
        "credential_id": _gap(run.get("credential_id")),
        "determination": _gap(run.get("determination")),
        "inputs": inputs,
        "outcome": outcome,
        "recorded_at": time.time(),
        "roster": roster,
        "schema_version": SCHEMA_VERSION,
        "weakness_ledger": _gap(run.get("weakness_ledger")),
    }

    record["checksum"] = _checksum(record)
    return record


def validate_schema(record):
    """Check a record against the current schema version.

    Returns {valid: bool, errors: [...]}.
    """
    errors = []

    if not isinstance(record, dict):
        return {"valid": False, "errors": ["record is not a dict"]}

    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version mismatch: expected {SCHEMA_VERSION}, got {record.get('schema_version')}")

    for field in _TOP_FIELDS:
        if field not in record:
            errors.append(f"missing top-level field: {field}")

    # Check inputs sub-fields
    inputs = record.get("inputs")
    if isinstance(inputs, dict):
        for f in _INPUT_FIELDS:
            if f not in inputs:
                errors.append(f"missing inputs field: {f}")
    elif inputs != GAP:
        errors.append("inputs is not a dict or gap marker")

    # Check outcome sub-fields
    outcome = record.get("outcome")
    if isinstance(outcome, dict):
        for f in _OUTCOME_FIELDS:
            if f not in outcome:
                errors.append(f"missing outcome field: {f}")
    elif outcome != GAP:
        errors.append("outcome is not a dict or gap marker")

    # Verify checksum
    if "checksum" in record:
        expected = _checksum(record)
        if record["checksum"] != expected:
            errors.append("checksum mismatch")

    return {"valid": len(errors) == 0, "errors": errors}


def roundtrip_check(run):
    """Serialize then deserialize a run, verify equality. Returns bool."""
    try:
        rec = record_run(run)
        serialized = json.dumps(rec, sort_keys=True, default=str)
        deserialized = json.loads(serialized)
        return rec == deserialized
    except Exception:
        return False


def persist_run(record):
    """Write a record to the Supabase cade_run_ledger table. Fail-soft."""
    if not ENABLED:
        return {"persisted": False, "reason": "disabled"}
    try:
        row = {
            "schema_version": record.get("schema_version", SCHEMA_VERSION),
            "payload": json.dumps(record, sort_keys=True, default=str),
            "checksum": record.get("checksum", ""),
            "recorded_at": record.get("recorded_at", time.time()),
        }
        db.insert("cade_run_ledger", row)
        return {"persisted": True}
    except Exception as e:
        return {"persisted": False, "reason": str(e)}


# ─── Stats ───

_call_count = 0
_persist_count = 0
_error_count = 0


def stats():
    """Module statistics."""
    return {
        "module": "cade_run_ledger",
        "schema_version": SCHEMA_VERSION,
        "enabled": ENABLED,
        "calls": _call_count,
        "persists": _persist_count,
        "errors": _error_count,
    }
