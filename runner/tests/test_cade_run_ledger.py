import os
import sys
import json

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import cade_run_ledger


def _full_run():
    return {
        "inputs": {
            "mandate": "Enforce zoning setback",
            "recipient": "Board of Appeals",
            "facts": ["Lot is 50ft wide", "Setback requires 10ft"],
        },
        "weakness_ledger": [{"issue": "no survey", "weight": 0.3}],
        "alignment_ledger": [{"signal": "precedent match", "score": 0.9}],
        "determination": "approve",
        "credential_id": "cred-abc-123",
        "roster": [
            {"bot": "drafter-1", "position": "lead"},
            {"bot": "reviewer-2", "position": "checker"},
        ],
        "outcome": {
            "prevailed": True,
            "rfis_raised": 2,
            "ruling": "Setback variance granted",
        },
    }


def test_complete_run_records_all_fields():
    run = _full_run()
    rec = cade_run_ledger.record_run(run)
    assert rec["schema_version"] == "1.0"
    assert rec["inputs"]["mandate"] == "Enforce zoning setback"
    assert rec["inputs"]["recipient"] == "Board of Appeals"
    assert rec["inputs"]["facts"] == ["Lot is 50ft wide", "Setback requires 10ft"]
    assert rec["determination"] == "approve"
    assert rec["credential_id"] == "cred-abc-123"
    assert rec["outcome"]["prevailed"] is True
    assert rec["outcome"]["rfis_raised"] == 2
    assert rec["outcome"]["ruling"] == "Setback variance granted"
    assert len(rec["roster"]) == 2
    assert rec["roster"][0]["bot"] == "drafter-1"
    assert "checksum" in rec
    assert "recorded_at" in rec


def test_missing_fields_get_gap_markers():
    rec = cade_run_ledger.record_run({})
    gap = cade_run_ledger.GAP
    assert rec["inputs"]["mandate"] == gap
    assert rec["inputs"]["recipient"] == gap
    assert rec["inputs"]["facts"] == gap
    assert rec["weakness_ledger"] == gap
    assert rec["alignment_ledger"] == gap
    assert rec["determination"] == gap
    assert rec["credential_id"] == gap
    assert rec["roster"] == gap
    assert rec["outcome"]["prevailed"] == gap
    assert rec["outcome"]["rfis_raised"] == gap
    assert rec["outcome"]["ruling"] == gap
    # No exception was raised
    assert rec["schema_version"] == "1.0"


def test_missing_fields_no_exceptions():
    """Calling record_run with None or non-dict never raises."""
    rec1 = cade_run_ledger.record_run(None)
    assert rec1["schema_version"] == "1.0"
    rec2 = cade_run_ledger.record_run("not a dict")
    assert rec2["schema_version"] == "1.0"


def test_schema_version_is_set():
    rec = cade_run_ledger.record_run(_full_run())
    assert rec["schema_version"] == cade_run_ledger.SCHEMA_VERSION
    assert rec["schema_version"] == "1.0"


def test_roundtrip_serialization():
    run = _full_run()
    assert cade_run_ledger.roundtrip_check(run) is True


def test_roundtrip_empty_run():
    assert cade_run_ledger.roundtrip_check({}) is True


def test_validate_schema_valid():
    rec = cade_run_ledger.record_run(_full_run())
    result = cade_run_ledger.validate_schema(rec)
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_schema_catches_invalid():
    result = cade_run_ledger.validate_schema({})
    assert result["valid"] is False
    assert len(result["errors"]) > 0


def test_validate_schema_bad_version():
    rec = cade_run_ledger.record_run(_full_run())
    rec["schema_version"] = "99.0"
    rec["checksum"] = "tampered"
    result = cade_run_ledger.validate_schema(rec)
    assert result["valid"] is False
    assert any("schema_version" in e for e in result["errors"])


def test_deterministic_output():
    run = _full_run()
    rec1 = cade_run_ledger.record_run(run)
    rec2 = cade_run_ledger.record_run(run)
    # Exclude recorded_at which is time-based
    r1 = {k: v for k, v in rec1.items() if k not in ("recorded_at", "checksum")}
    r2 = {k: v for k, v in rec2.items() if k not in ("recorded_at", "checksum")}
    assert r1 == r2
    # Sorted keys in JSON serialization
    s1 = json.dumps(r1, sort_keys=True)
    s2 = json.dumps(r2, sort_keys=True)
    assert s1 == s2


def test_stats_output():
    s = cade_run_ledger.stats()
    assert s["module"] == "cade_run_ledger"
    assert s["schema_version"] == "1.0"
    assert "enabled" in s
    assert "calls" in s
    assert "persists" in s
    assert "errors" in s


def test_disabled_via_env_flag(monkeypatch):
    monkeypatch.setattr(cade_run_ledger, "ENABLED", False)
    rec = cade_run_ledger.record_run(_full_run())
    assert rec.get("disabled") is True
    assert rec["schema_version"] == "1.0"
    # Should not have full fields
    assert "inputs" not in rec
