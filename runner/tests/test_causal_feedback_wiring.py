"""The causal-feedback loop must actually be CLOSED, not merely implemented.

causal_feedback shipped with its schema, its writer and 59 unit tests, but no
module in the orchestrator imported it — so nothing ever wrote a row and
lookup() could only answer from an empty table. These tests assert the wiring
itself, which is the part that was missing: a unit-tested writer nobody calls
is indistinguishable from no writer at all.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import causal_feedback
import improvement_verify


def _proposal(**over):
    p = {
        "id": "prop-1",
        "task_slug": "improve-cycle-time",
        "surface": "runner",
        "metric_name": "Median cycle time",
        "metric_collector": "cycle_time_hours",
        "predicted_multiplier": 2.0,
        "artifact_commit": None,
        "artifact_repo": None,
        "app": "beethoven",
    }
    p.update(over)
    return p


def _settle(proposal, injected, **kw):
    """Run settle() with every external side effect stubbed except the one under test."""
    with patch.object(improvement_verify.db, "update", return_value=None), \
         patch.object(improvement_verify.db, "insert", return_value=None), \
         patch.object(improvement_verify.db, "select", return_value=[]), \
         patch.object(improvement_verify.gate_liveness, "record", return_value=None), \
         patch.object(improvement_verify, "revert_commit",
                      return_value={"ok": False, "detail": "stubbed"}):
        return improvement_verify.settle(proposal, injected=injected, **kw)


def test_a_validated_settlement_writes_causal_feedback():
    p = _proposal(baseline_value=100.0, comparator="lt", required_margin=1.5)
    with patch.object(causal_feedback, "write", return_value=None) as w:
        res = _settle(p, injected=25.0)
    assert res["verdict"] == "validated"
    w.assert_called_once()
    kwargs = w.call_args.kwargs
    assert kwargs["bottleneck_key"] == "cycle_time_hours"
    assert kwargs["remediation_slug"] == "improve-cycle-time"
    assert kwargs["signal_before"] == 100.0
    assert kwargs["signal_after"] == 25.0
    assert kwargs["metadata"]["verdict"] == "validated"


def test_a_regressed_settlement_also_writes_causal_feedback():
    # The negative half is what teaches lookup() a mapping is spurious, so it
    # must not be the half that goes unrecorded.
    p = _proposal(baseline_value=100.0, comparator="lt", required_margin=1.5)
    with patch.object(causal_feedback, "write", return_value=None) as w:
        res = _settle(p, injected=180.0)
    assert res["verdict"] == "regressed"
    w.assert_called_once()
    assert w.call_args.kwargs["metadata"]["verdict"] == "regressed"


def test_unmeasurable_settlement_writes_nothing():
    p = _proposal(baseline_value=None)
    with patch.object(causal_feedback, "write", return_value=None) as w:
        res = _settle(p, injected=25.0)
    assert res["verdict"] == "unmeasurable"
    w.assert_not_called()


def test_a_non_positive_baseline_is_not_attributed():
    # signal_before is the delta denominator; 0 is unattributable, not an error.
    p = _proposal(baseline_value=0.0, comparator="lt", required_margin=1.5)
    with patch.object(causal_feedback, "write", return_value=None) as w:
        _settle(p, injected=25.0)
    w.assert_not_called()


def test_a_proposal_with_no_metric_key_is_not_attributed():
    p = _proposal(baseline_value=100.0, comparator="lt", required_margin=1.5,
                  metric_collector=None, metric_name=None)
    with patch.object(causal_feedback, "write", return_value=None) as w:
        _settle(p, injected=25.0)
    w.assert_not_called()


def test_a_failing_feedback_write_never_changes_the_verdict():
    # Fail-soft is the module's stated contract: feedback must not be able to
    # hold up a settlement or a rollback.
    p = _proposal(baseline_value=100.0, comparator="lt", required_margin=1.5)
    with patch.object(causal_feedback, "write", side_effect=RuntimeError("db down")):
        res = _settle(p, injected=25.0)
    assert res["verdict"] == "validated"
    assert res["acted"] is True
