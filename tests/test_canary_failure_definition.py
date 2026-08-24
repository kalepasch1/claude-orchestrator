"""One explicit definition of "failure" in the canary flow, and the gauge follows it.

"Failure" was never written down: `verdict == "promote"` was compared inline in three
places, so each site independently decided what an absent or unrecognised verdict meant.
And the gauge was only ever written by main(), so a caller using `evaluate()` as a library
got a verdict while canary_last_success kept the PREVIOUS success timestamp — an alert on
gauge staleness stayed quiet through exactly the failure it exists to catch.

These tests pin the definition, and pin that the unknown cases fail CLOSED. This gauge
gates a deploy; reading "I could not tell" as success is how a broken evaluator promotes
a broken release.
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import canary  # noqa: E402


@pytest.fixture(autouse=True)
def reset_gauge():
    canary.set_gauge("canary_last_success", 0)
    yield
    canary.set_gauge("canary_last_success", 0)


# --- the definition -------------------------------------------------------------------

def test_promote_is_the_only_success():
    assert canary.is_failure({"verdict": "promote", "reason": "all within thresholds"}) is False


def test_rollback_is_a_failure():
    assert canary.is_failure({"verdict": "rollback", "reason": "error_rate=0.9"}) is True


def test_unrecognised_verdict_fails_closed():
    assert canary.is_failure({"verdict": "maybe"}) is True


def test_missing_verdict_fails_closed():
    assert canary.is_failure({"reason": "evaluator crashed"}) is True


@pytest.mark.parametrize("bad", [None, "", [], "promote", 0, object()])
def test_non_dict_result_fails_closed(bad):
    assert canary.is_failure(bad) is True


def test_verdict_is_matched_exactly_not_loosely():
    for near in ("Promote", "PROMOTE", " promote", "promoted"):
        assert canary.is_failure({"verdict": near}) is True, near


# --- failure_reason -------------------------------------------------------------------

def test_success_has_no_reason():
    assert canary.failure_reason({"verdict": "promote"}) is None


def test_rollback_reason_is_carried_through():
    reason = canary.failure_reason({"verdict": "rollback", "reason": "p95_ms=900 breaches max 500"})
    assert "p95_ms=900" in reason


def test_reason_is_never_empty_for_a_failure():
    for result in ({"verdict": "rollback"}, {"verdict": "maybe"}, {}, None, "x"):
        reason = canary.failure_reason(result)
        assert reason and reason.strip(), f"empty reason for {result!r}"


def test_unrecognised_verdict_is_named_in_the_reason():
    assert "maybe" in canary.failure_reason({"verdict": "maybe"})


# --- gauge --------------------------------------------------------------------------

def test_success_stamps_the_gauge():
    assert canary.record_result({"verdict": "promote"}) is True
    assert canary.get_gauge("canary_last_success") > 0


def test_failure_zeroes_the_gauge_rather_than_leaving_a_stale_success():
    """The regression: a rollback used to leave the previous success timestamp standing."""
    canary.record_result({"verdict": "promote"})
    assert canary.get_gauge("canary_last_success") > 0
    assert canary.record_result({"verdict": "rollback", "reason": "boom"}) is False
    assert canary.get_gauge("canary_last_success") == 0


def test_unknown_verdict_also_zeroes_the_gauge():
    canary.record_result({"verdict": "promote"})
    canary.record_result({"verdict": "???"})
    assert canary.get_gauge("canary_last_success") == 0


def test_library_path_updates_the_gauge(monkeypatch):
    """evaluate_and_record exists because plain evaluate() left the gauge untouched."""
    canary.record_result({"verdict": "promote"})
    monkeypatch.setattr(canary, "evaluate",
                        lambda url=None: {"verdict": "rollback", "reason": "error_rate"})
    out = canary.evaluate_and_record("http://x/metrics")
    assert out["verdict"] == "rollback"
    assert canary.get_gauge("canary_last_success") == 0


def test_heartbeat_reads_the_zeroed_gauge_as_not_succeeding():
    """A failure must not leave a heartbeat age that looks like a recent success.

    heartbeat_age() documents None as "no successful evaluation to measure from", which
    is what a zeroed gauge means; heartbeat_expired() therefore reports expired.
    """
    canary.record_result({"verdict": "promote"})
    assert canary.heartbeat_age() is not None
    canary.record_result({"verdict": "rollback", "reason": "boom"})
    assert canary.heartbeat_age() is None
    assert canary.heartbeat_expired() is True


# --- exit code agrees with the gauge ---------------------------------------------------

def test_main_exit_code_and_gauge_agree_on_failure(monkeypatch, capsys):
    monkeypatch.setattr(canary, "evaluate",
                        lambda url=None: {"verdict": "rollback", "reason": "error_rate=1.0"})
    rc = canary.main([])
    capsys.readouterr()
    assert rc == 1
    assert canary.get_gauge("canary_last_success") == 0


def test_main_exit_code_and_gauge_agree_on_success(monkeypatch, capsys):
    monkeypatch.setattr(canary, "evaluate", lambda url=None: {"verdict": "promote"})
    rc = canary.main([])
    capsys.readouterr()
    assert rc == 0
    assert canary.get_gauge("canary_last_success") > 0


def test_main_treats_an_unparseable_verdict_as_a_failed_run(monkeypatch, capsys):
    monkeypatch.setattr(canary, "evaluate", lambda url=None: {"reason": "evaluator crashed"})
    rc = canary.main([])
    capsys.readouterr()
    assert rc == 1, "an evaluation that did not complete must not exit 0"
    assert canary.get_gauge("canary_last_success") == 0
