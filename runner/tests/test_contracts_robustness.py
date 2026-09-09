"""KPI contract: the inputs that validated when they should not have.

`validate_kpi_record` is the gate in front of the deploy-KPI row. Everything it
lets through is written and later averaged, so a value that passes validation but
is not a number is worse than one that raises — it silently poisons the column.

Four defects, all confirmed against the code before the fix:

    duration_seconds=True            -> (True, None)   bool is a subclass of int
    duration_seconds=float('nan')    -> (True, None)   nan < 0 is False
    duration_seconds=float('inf')    -> (True, None)   same, and not JSON-representable
    KPIRecord.from_dict(d)           -> mutated d      status rewritten to an enum
                                                        in the CALLER's dictionary

None of these raised. Each produced a record that looked valid, which is why the
existing 44 tests were green over all of them.

The last one is not a validation bug but an aliasing one: `from_dict` wrote back
into the dict it was handed, so a caller that built a record and then re-read or
re-serialised its own dict found a DeployStatus where it had put a string.
"""
import math
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(RUNNER))

from runner.contracts import (  # noqa: E402
    DeployStatus, KPIRecord, validate_kpi_record,
)

VALID = {"deploy_id": "deploy-1", "timestamp": "2026-09-09T12:00:00Z",
         "status": "succeeded"}


def rec(**over):
    return dict(VALID, **over)


# ── the baseline still holds ────────────────────────────────────────────────

def test_a_well_formed_record_validates():
    assert validate_kpi_record(rec()) == (True, None)


def test_a_real_duration_still_validates():
    assert validate_kpi_record(rec(duration_seconds=12.5))[0] is True
    assert validate_kpi_record(rec(duration_seconds=0))[0] is True
    assert validate_kpi_record(rec(duration_seconds=3))[0] is True


def test_a_negative_duration_is_still_rejected():
    ok, err = validate_kpi_record(rec(duration_seconds=-1))
    assert ok is False and "negative" in err


# ── duration_seconds: values that passed and should not have ────────────────

def test_a_boolean_duration_is_rejected():
    """`isinstance(True, int)` is True, so True validated as a number.

    It then reaches the payload as `true`, which is not a duration in any
    reading, and any average over the column silently treats it as 1.
    """
    ok, err = validate_kpi_record(rec(duration_seconds=True))
    assert ok is False
    assert "number" in err


def test_false_is_rejected_too_and_not_confused_with_zero():
    # `False == 0` is True in Python, so a bool would otherwise masquerade as a
    # legitimate zero-second deploy.
    ok, _ = validate_kpi_record(rec(duration_seconds=False))
    assert ok is False


def test_nan_is_rejected():
    """`nan < 0` is False, so the negative check waved NaN through.

    One NaN makes every mean over the duration column NaN — the metric is gone,
    not merely wrong, and nothing points at the row that did it.
    """
    ok, err = validate_kpi_record(rec(duration_seconds=float("nan")))
    assert ok is False
    assert "finite" in err


def test_positive_and_negative_infinity_are_rejected():
    for value in (float("inf"), float("-inf")):
        ok, err = validate_kpi_record(rec(duration_seconds=value))
        assert ok is False, value
        assert "finite" in err or "negative" in err


def test_a_string_duration_is_still_rejected():
    ok, err = validate_kpi_record(rec(duration_seconds="12"))
    assert ok is False and "number" in err


def test_an_explicit_none_duration_is_allowed():
    # The field is Optional; absent and null are both "not measured".
    assert validate_kpi_record(rec(duration_seconds=None))[0] is True


# ── from_dict no longer edits the caller's dict ─────────────────────────────

def test_from_dict_does_not_mutate_its_argument():
    """The aliasing bug.

    A caller that builds a record and then re-reads or re-serialises the SAME
    dict used to find a DeployStatus where it had put a string.
    """
    source = rec()
    KPIRecord.from_dict(source)
    assert source["status"] == "succeeded"
    assert type(source["status"]) is str
    assert not isinstance(source["status"], DeployStatus)


def test_from_dict_still_produces_an_enum_on_the_record():
    record = KPIRecord.from_dict(rec())
    assert record.status is DeployStatus.SUCCEEDED


def test_the_round_trip_gives_back_the_plain_string():
    assert KPIRecord.from_dict(rec()).to_dict()["status"] == "succeeded"


def test_from_dict_is_repeatable_on_the_same_dict():
    # Previously the second call received an enum rather than a string; it
    # happened to work, but only because the branch was guarded by isinstance.
    source = rec()
    first = KPIRecord.from_dict(source)
    second = KPIRecord.from_dict(source)
    assert first == second


def test_an_already_enum_status_is_accepted():
    record = KPIRecord.from_dict(rec(status=DeployStatus.FAILED))
    assert record.status is DeployStatus.FAILED


# ── from_dict tolerates an upstream that adds a field ───────────────────────

def test_an_unknown_key_is_ignored_rather_than_raising():
    """`cls(**data)` raised TypeError on any extra key.

    These records come from a deploy path whose discipline is that telemetry
    must never fail the deploy; a field added upstream should not raise inside
    it.
    """
    record = KPIRecord.from_dict(rec(commit_sha="abc123", region="us-east"))
    assert record.deploy_id == "deploy-1"


def test_an_unknown_status_still_raises():
    # Deliberately NOT tolerated: the status IS the record. Silently defaulting
    # a status nobody recognises would report an unknown outcome as a known one.
    with pytest.raises(ValueError):
        KPIRecord.from_dict(rec(status="exploded"))


def test_a_missing_required_field_still_raises():
    with pytest.raises(TypeError):
        KPIRecord.from_dict({"deploy_id": "d"})


def test_a_non_dict_gets_a_clear_type_error():
    with pytest.raises(TypeError) as exc:
        KPIRecord.from_dict(["not", "a", "dict"])
    assert "dict" in str(exc.value)


# ── the status vocabulary is precomputed, not rebuilt per call ──────────────

def test_the_error_message_lists_the_allowed_statuses():
    ok, err = validate_kpi_record(rec(status="bogus"))
    assert ok is False
    for value in (s.value for s in DeployStatus):
        assert value in err
    assert "bogus" in err


def test_every_declared_status_validates():
    for status in DeployStatus:
        assert validate_kpi_record(rec(status=status.value))[0] is True, status


def test_a_non_string_status_is_rejected():
    ok, err = validate_kpi_record(rec(status=1))
    assert ok is False and "string" in err


# ── unchanged behaviour worth keeping pinned ────────────────────────────────

def test_a_non_dict_record_is_rejected_without_raising():
    assert validate_kpi_record(None)[0] is False
    assert validate_kpi_record("nope")[0] is False
    assert validate_kpi_record([])[0] is False


def test_a_malformed_timestamp_is_rejected():
    assert validate_kpi_record(rec(timestamp="09/09/2026"))[0] is False
    assert validate_kpi_record(rec(timestamp=""))[0] is False


def test_a_calendar_impossible_timestamp_is_rejected():
    # Matches the shape but is not a real datetime; the regex alone would pass.
    ok, err = validate_kpi_record(rec(timestamp="2026-02-30T00:00:00Z"))
    assert ok is False and "valid ISO-8601" in err


def test_a_non_string_error_message_is_rejected():
    assert validate_kpi_record(rec(status="failed", error_message=object()))[0] is False
