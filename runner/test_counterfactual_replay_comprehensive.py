#!/usr/bin/env python3
"""Comprehensive unit tests for counterfactual_replay.py.

SUITE OWNERSHIP (five suites exist for this one module; see the cluster notes
in the sibling files):
    * THIS FILE owns the pure, per-decision surface: replay_decision,
      replay_decision_safe, replay_decision_with_context, compare_model_outputs,
      detect_version_upgrade, calculate_confidence_change, analyze_replay_impact,
      track_data_evolution, filter_decisions and is_empty_history.
    * test_counterfactual_replay_spec.py owns divergence/policy application and
      the ORCH_COUNTERFACTUAL_* configuration contract.
    * test_counterfactual_replay_impl.py owns the batch surface, RouteConfig and
      the runtime-path helpers.
    * tests/test_counterfactual_replay.py owns persistence and module counters.
    * tests/test_counterfactual_replay_e2e.py owns the assembled pipeline.

This file was previously written against a `db.select`/model-roster design that
counterfactual_replay.py has never had (no `db` import, no `_fetch_recent_decisions`,
no `run_replay`). Every test below was rewritten against the API the module
actually exports; where the original intent had no counterpart, the nearest real
behaviour is asserted and the substitution is named in a comment.
"""

import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.abspath(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import counterfactual_replay as cfr


class FakeModel:
    """Stands in for a model handle: model_id/version plus evaluate()."""

    def __init__(self, model_id="opus", version="2.0", decision="route_b",
                 confidence=0.9, raises=None):
        self.model_id = model_id
        self.version = version
        self._decision = decision
        self._confidence = confidence
        self._raises = raises
        self.calls = []

    def evaluate(self, input_data, task_type):
        self.calls.append((input_data, task_type))
        if self._raises:
            raise self._raises
        return {"decision": self._decision, "confidence": self._confidence}


class InertModel:
    """A model handle with no evaluate() — replay records provenance only."""

    def __init__(self, model_id="sonnet", version="1.5"):
        self.model_id = model_id
        self.version = version


# =============================================================================
# replay_decision()
# =============================================================================

class TestReplayDecision:
    """Tests for replay_decision(task_id, old_decision, new_model)."""

    def test_returns_none_for_non_dict_decision(self):
        """A non-dict decision is not replayable."""
        assert cfr.replay_decision("t1", "not-a-dict", FakeModel()) is None

    def test_returns_none_for_empty_decision(self):
        """An empty decision carries neither input nor output."""
        assert cfr.replay_decision("t1", {}, FakeModel()) is None

    def test_returns_none_when_neither_input_nor_output(self):
        """Metadata-only records are skipped: there is nothing to re-evaluate."""
        decision = {"task_id": "t1", "model": "haiku", "state": "DONE"}
        assert cfr.replay_decision("t1", decision, FakeModel()) is None

    def test_returns_none_for_corrupted_string_output(self):
        """A non-empty string output is treated as corrupted and skipped."""
        decision = {"task_id": "t1", "output": "malformed", "input": {}}
        assert cfr.replay_decision("t1", decision, FakeModel()) is None

    def test_empty_string_output_is_replayable(self):
        """An empty-string output is a recorded no-answer, not corruption."""
        decision = {"task_id": "t1", "output": "", "input": {"q": 1}}
        result = cfr.replay_decision("t1", decision, FakeModel())
        assert result is not None
        assert result["task_id"] == "t1"

    def test_returns_none_when_input_is_none(self):
        """An explicit null input cannot be fed to the new model."""
        decision = {"task_id": "t1", "input": None, "output": {"route": "a"}}
        assert cfr.replay_decision("t1", decision, FakeModel()) is None

    def test_records_new_model_identity(self):
        """The replay records which model produced the new answer."""
        decision = {"task_id": "t1", "input": {"q": 1}}
        result = cfr.replay_decision("t1", decision, FakeModel("opus", "2.0"))
        assert result["model"] == "opus"
        assert result["model_version"] == "2.0"

    def test_unknown_model_identity_falls_back(self):
        """A model handle without model_id/version degrades to 'unknown'."""
        decision = {"task_id": "t1", "input": {"q": 1}}
        result = cfr.replay_decision("t1", decision, object())
        assert result["model"] == "unknown"
        assert result["model_version"] == "unknown"

    def test_preserves_original_provenance(self):
        """Original task id, timestamp, model and version are preserved."""
        decision = {
            "task_id": "orig-1",
            "timestamp": "2026-08-18T10:00:00Z",
            "model": "haiku",
            "model_version": "1.0",
            "input": {"q": 1},
        }
        result = cfr.replay_decision("replay-1", decision, FakeModel())
        assert result["task_id"] == "replay-1"
        assert result["original_task_id"] == "orig-1"
        assert result["original_timestamp"] == "2026-08-18T10:00:00Z"
        assert result["original_model"] == "haiku"
        assert result["original_model_version"] == "1.0"

    def test_evaluate_receives_input_and_task_type(self):
        """The stored input and decision type are handed to the new model."""
        model = FakeModel()
        decision = {"task_id": "t1", "type": "build", "input": {"q": 1}}
        cfr.replay_decision("t1", decision, model)
        assert model.calls == [({"q": 1}, "build")]

    def test_task_type_defaults_to_routing(self):
        """Decisions with no recorded type replay as routing decisions."""
        model = FakeModel()
        cfr.replay_decision("t1", {"input": {"q": 1}}, model)
        assert model.calls[0][1] == "routing"

    def test_carries_over_context_keys(self):
        """user/repo/state travel with the replay for audit purposes."""
        decision = {
            "input": {"q": 1},
            "user": "kalepasch",
            "repo": "orchpush",
            "state": "DONE",
            "attempt": 3,
        }
        result = cfr.replay_decision("t1", decision, FakeModel())
        assert result["user"] == "kalepasch"
        assert result["repo"] == "orchpush"
        assert result["state"] == "DONE"
        # Only the three whitelisted keys are copied.
        assert "attempt" not in result

    def test_model_without_evaluate_yields_no_decision(self):
        """Without evaluate() the replay is provenance-only, not an answer."""
        result = cfr.replay_decision("t1", {"input": {"q": 1}}, InertModel())
        assert result["model"] == "sonnet"
        assert "decision" not in result
        assert "confidence" not in result

    def test_evaluate_failure_is_fail_soft(self):
        """A raising model yields None, never an exception to the caller."""
        model = FakeModel(raises=RuntimeError("model unavailable"))
        assert cfr.replay_decision("t1", {"input": {"q": 1}}, model) is None


# =============================================================================
# replay_decision_safe()
# =============================================================================

class TestReplayDecisionSafe:
    """Tests for replay_decision_safe() — the fail-soft wrapper."""

    def test_success_status_and_payload(self):
        """A replayable decision comes back with status=success plus fields."""
        decision = {"task_id": "t1", "input": {"q": 1}, "model": "haiku"}
        result = cfr.replay_decision_safe("t1", decision, FakeModel())
        assert result["status"] == "success"
        assert result["decision"] == "route_b"
        assert result["original_model"] == "haiku"

    def test_skipped_status_for_unreplayable(self):
        """Unreplayable input is reported as skipped, with a reason."""
        result = cfr.replay_decision_safe("t1", {}, FakeModel())
        assert result == {
            "task_id": "t1",
            "status": "skipped",
            "reason": "no_model_output",
        }

    def test_corrupted_decision_is_skipped_not_raised(self):
        """Corrupted records degrade to skipped rather than raising."""
        corrupted = {"task_id": None, "model": "", "input": None, "output": "malformed"}
        result = cfr.replay_decision_safe("t1", corrupted, FakeModel())
        assert result["status"] == "skipped"

    def test_model_error_collapses_to_skipped(self):
        """replay_decision swallows model errors, so 'partial' is unreachable.

        Substitution: the original test asserted a 'partial' status. That status
        is dead code — replay_decision() catches every exception itself and
        returns None — so the true, meaningful assertion is that a raising model
        surfaces as 'skipped' and never escapes.
        """
        model = FakeModel(raises=ValueError("boom"))
        result = cfr.replay_decision_safe("t1", {"input": {"q": 1}}, model)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_model_output"

    def test_task_id_always_present(self):
        """Every branch echoes the task id so results can be reconciled."""
        for decision in ({}, {"input": {"q": 1}}, {"output": "malformed"}):
            assert cfr.replay_decision_safe("t-42", decision, FakeModel())["task_id"] == "t-42"


# =============================================================================
# replay_decision_with_context()
# =============================================================================

class TestReplayDecisionWithContext:
    """Tests for replay_decision_with_context()."""

    def test_records_context_version(self):
        """The replay is stamped with the new context version."""
        decision = {"input": {"data": "old", "version": 1}}
        result = cfr.replay_decision_with_context(
            "t1", decision, FakeModel(), {"data": "new", "context_version": 5}
        )
        assert result["context_version"] == 5

    def test_context_version_defaults_to_two(self):
        """A context with no version is treated as the second generation."""
        decision = {"input": {"data": "old"}}
        result = cfr.replay_decision_with_context(
            "t1", decision, FakeModel(), {"data": "new"}
        )
        assert result["context_version"] == 2

    def test_records_data_evolution(self):
        """Old and new payloads are recorded side by side."""
        decision = {"input": {"data": "old-value"}}
        result = cfr.replay_decision_with_context(
            "t1", decision, FakeModel(), {"data": "new-value"}
        )
        assert result["data_evolution"] == {"old": "old-value", "new": "new-value"}

    def test_unreplayable_decision_returns_none(self):
        """Context does not rescue a decision that cannot be replayed."""
        assert cfr.replay_decision_with_context(
            "t1", {}, FakeModel(), {"data": "new"}
        ) is None


# =============================================================================
# compare_model_outputs()
# =============================================================================

class TestCompareModelOutputs:
    """Tests for compare_model_outputs()."""

    def test_reports_both_models_and_difference(self):
        """Two different models are reported as a difference."""
        result = cfr.compare_model_outputs(
            {"model": "haiku", "confidence": 0.7},
            {"model": "opus", "confidence": 0.9},
        )
        assert result["old_model"] == "haiku"
        assert result["new_model"] == "opus"
        assert result["difference"] is True

    def test_same_model_is_no_difference(self):
        """Identical model ids are not a difference."""
        result = cfr.compare_model_outputs({"model": "opus"}, {"model": "opus"})
        assert result["difference"] is False

    def test_confidence_delta_is_absolute(self):
        """The delta is a magnitude, so argument order does not change it."""
        forward = cfr.compare_model_outputs(
            {"model": "a", "confidence": 0.2}, {"model": "b", "confidence": 0.9})
        backward = cfr.compare_model_outputs(
            {"model": "b", "confidence": 0.9}, {"model": "a", "confidence": 0.2})
        assert forward["confidence_delta"] == pytest.approx(0.7)
        assert backward["confidence_delta"] == pytest.approx(0.7)

    def test_missing_confidence_defaults_to_zero(self):
        """Outputs without confidence compare at 0.0."""
        result = cfr.compare_model_outputs({"model": "a"}, {"model": "b"})
        assert result["old_confidence"] == 0.0
        assert result["new_confidence"] == 0.0
        assert result["confidence_delta"] == 0.0

    def test_non_dict_outputs_degrade_to_unknown(self):
        """Non-dict outputs report unknown models rather than raising."""
        result = cfr.compare_model_outputs(None, ["not", "a", "dict"])
        assert result["old_model"] == "unknown"
        assert result["new_model"] == "unknown"
        assert result["difference"] is False

    def test_unsubtractable_confidence_fails_soft(self):
        """Non-numeric confidences fall back to the neutral comparison."""
        result = cfr.compare_model_outputs(
            {"model": "a", "confidence": "high"},
            {"model": "b", "confidence": "low"},
        )
        assert result == {"difference": False, "confidence_delta": 0.0}


# =============================================================================
# detect_version_upgrade() / calculate_confidence_change()
# =============================================================================

class TestVersionAndConfidenceMath:
    """Tests for detect_version_upgrade() and calculate_confidence_change()."""

    def test_version_change_detected(self):
        """A different version string counts as an upgrade."""
        assert cfr.detect_version_upgrade("1.0", "2.0") is True

    def test_identical_version_not_an_upgrade(self):
        """The same version is not a change."""
        assert cfr.detect_version_upgrade("2.0", "2.0") is False

    def test_missing_version_is_not_an_upgrade(self):
        """Absent versions cannot be compared, so no upgrade is claimed."""
        assert cfr.detect_version_upgrade(None, "2.0") is False
        assert cfr.detect_version_upgrade("1.0", None) is False
        assert cfr.detect_version_upgrade("", "") is False

    def test_version_compared_as_string(self):
        """Comparison is textual: 1 and '1' are the same version."""
        assert cfr.detect_version_upgrade(1, "1") is False
        # Direction is not detected — a rollback also reports True.
        assert cfr.detect_version_upgrade("2.0", "1.0") is True

    def test_confidence_change_is_signed(self):
        """A drop in confidence is reported as a negative change."""
        assert cfr.calculate_confidence_change(0.9, 0.4) == -0.5
        assert cfr.calculate_confidence_change(0.4, 0.9) == 0.5

    def test_confidence_change_rounds_to_two_places(self):
        """Changes are rounded to two decimals for stable reporting."""
        assert cfr.calculate_confidence_change(0.123456, 0.987654) == 0.86

    def test_confidence_change_fails_soft(self):
        """None and non-numeric inputs report no change instead of raising."""
        assert cfr.calculate_confidence_change(None, None) == 0.0
        assert cfr.calculate_confidence_change("high", 0.5) == 0.0


# =============================================================================
# analyze_replay_impact()
# =============================================================================

class TestAnalyzeReplayImpact:
    """Tests for analyze_replay_impact()."""

    def test_reports_confidence_and_model_change(self):
        """Impact covers confidence movement and whether the model changed."""
        old = {"model": "haiku", "output": {"route": "a", "confidence": 0.6}}
        replay = {"model": "opus", "decision": "b", "confidence": 0.9}
        impact = cfr.analyze_replay_impact(old, replay)
        assert impact["confidence_change"] == 0.3
        assert impact["model_changed"] is True

    def test_decision_stable_when_route_matches(self):
        """A replay that reproduces the stored route is stable."""
        old = {"model": "opus", "output": {"route": "a", "confidence": 0.8}}
        replay = {"model": "opus", "decision": "a", "confidence": 0.8}
        impact = cfr.analyze_replay_impact(old, replay)
        assert impact["decision_stable"] is True
        assert impact["model_changed"] is False

    def test_non_dict_output_scores_zero_confidence(self):
        """A corrupted stored output is treated as zero prior confidence."""
        impact = cfr.analyze_replay_impact(
            {"model": "haiku", "output": "malformed"},
            {"model": "opus", "decision": "b", "confidence": 0.5},
        )
        assert impact["confidence_change"] == 0.5

    def test_bad_input_returns_empty_impact(self):
        """An unusable decision yields an empty impact rather than raising."""
        assert cfr.analyze_replay_impact(None, {"decision": "b"}) == {}


# =============================================================================
# track_data_evolution()
# =============================================================================

class TestTrackDataEvolution:
    """Tests for track_data_evolution()."""

    def test_versions_default_when_absent(self):
        """Untagged payloads default to generations 1 and 2."""
        evolution = cfr.track_data_evolution({"a": 1}, {"a": 1})
        assert evolution["old_version"] == 1
        assert evolution["new_version"] == 2

    def test_explicit_versions_preserved(self):
        """Recorded versions are carried through."""
        evolution = cfr.track_data_evolution({"version": 3}, {"version": 7})
        assert evolution["old_version"] == 3
        assert evolution["new_version"] == 7

    def test_identical_payloads_have_no_changes(self):
        """Equal payloads produce an empty change list."""
        assert cfr.track_data_evolution({"a": 1, "b": 2}, {"a": 1, "b": 2})["changes"] == []

    def test_changed_keys_listed_sorted(self):
        """Changed and added keys are listed in sorted order."""
        evolution = cfr.track_data_evolution({"b": 1, "a": 1}, {"a": 2, "b": 1, "c": 3})
        assert evolution["changes"] == ["a", "c"]

    def test_version_key_never_reported_as_a_change(self):
        """The version tag itself is not a data change."""
        evolution = cfr.track_data_evolution({"version": 1, "a": 1}, {"version": 2, "a": 1})
        assert evolution["changes"] == []

    def test_old_and_new_values_recorded_per_change(self):
        """Each changed key gets an explicit before/after pair."""
        evolution = cfr.track_data_evolution({"route": "a"}, {"route": "b"})
        assert evolution["route_old"] == "a"
        assert evolution["route_new"] == "b"

    def test_non_dict_payloads_report_no_changes(self):
        """Non-dict payloads cannot be diffed, so nothing is claimed."""
        assert cfr.track_data_evolution("old", "new")["changes"] == []


# =============================================================================
# filter_decisions() / is_empty_history()
# =============================================================================

class TestFilterDecisions:
    """Tests for filter_decisions() — the replay-window selector.

    Substitution: the original tests here drove a `_fetch_recent_decisions()`
    DB query that this module has never had. filter_decisions() is the real
    function that narrows a decision history by type and date window, so the
    windowing intent is asserted against it.
    """

    DECISIONS = [
        {"task_id": "t1", "type": "routing", "timestamp": "2026-08-01"},
        {"task_id": "t2", "type": "build", "timestamp": "2026-08-15"},
        {"task_id": "t3", "type": "routing", "timestamp": "2026-08-18"},
    ]

    def test_empty_history_returns_empty(self):
        """No history means no decisions to replay."""
        assert cfr.filter_decisions([]) == []
        assert cfr.filter_decisions(None) == []

    def test_no_filters_returns_everything(self):
        """An unfiltered call is the identity over the history."""
        assert cfr.filter_decisions(self.DECISIONS) == self.DECISIONS

    def test_filters_by_task_type(self):
        """Only decisions of the requested type survive."""
        routing = cfr.filter_decisions(self.DECISIONS, task_type="routing")
        assert [d["task_id"] for d in routing] == ["t1", "t3"]

    def test_filters_by_date_window(self):
        """The lookback window is inclusive on both ends."""
        recent = cfr.filter_decisions(
            self.DECISIONS, start_date="2026-08-10", end_date="2026-08-19")
        assert [d["task_id"] for d in recent] == ["t2", "t3"]

    def test_start_date_alone_is_an_open_window(self):
        """A start date with no end keeps everything at or after it."""
        recent = cfr.filter_decisions(self.DECISIONS, start_date="2026-08-15")
        assert [d["task_id"] for d in recent] == ["t2", "t3"]

    def test_type_and_date_filters_combine(self):
        """Both filters apply together, not alternatively."""
        selected = cfr.filter_decisions(
            self.DECISIONS, task_type="routing", start_date="2026-08-10")
        assert [d["task_id"] for d in selected] == ["t3"]

    def test_non_dict_entries_are_dropped(self):
        """Malformed history entries are skipped, not fatal."""
        assert cfr.filter_decisions([None, "junk", {"task_id": "t9"}]) == [{"task_id": "t9"}]

    def test_is_empty_history(self):
        """is_empty_history() is the guard the replay loop opens with."""
        assert cfr.is_empty_history([]) is True
        assert cfr.is_empty_history(None) is True
        assert cfr.is_empty_history([{"task_id": "t1"}]) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
