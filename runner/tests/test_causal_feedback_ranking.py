"""The learning loop must close: evidence has to reach the action selection.

causal_feedback.py's docstring says lookup() exists so the "router queries to weight next
action selection", and write() records an outcome on every task completion. On
origin/master the writes happen and NOTHING reads them — grep finds no caller of
causal_feedback anywhere in runner/. rank_remediations is the consuming half, kept pure
with the DB read injected so the selection rule is testable without a database.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import causal_feedback as cf  # noqa: E402


def _row(slug, positive=0, negative=0, neutral=0, confidence=0.9, delta=0.0):
    return {"remediation_slug": slug, "positive_count": positive,
            "negative_count": negative, "neutral_count": neutral,
            "avg_confidence": confidence, "avg_delta_pct": delta}


def _lookup(*rows):
    return lambda _key, _floor=None: list(rows)


class TestRanking:
    def test_a_proven_remediation_outranks_an_unproven_one(self):
        ranked = cf.rank_remediations(
            "cycle_time_hours", ["untried", "proven"],
            lookup_fn=_lookup(_row("proven", positive=3)))
        assert ranked == ["proven", "untried"]

    def test_a_harmful_remediation_sinks_below_an_unproven_one(self):
        """No evidence must beat evidence of harm — that is the point of scoring 0.0."""
        ranked = cf.rank_remediations(
            "cycle_time_hours", ["harmful", "untried"],
            lookup_fn=_lookup(_row("harmful", negative=4)))
        assert ranked == ["untried", "harmful"]

    def test_more_positives_wins(self):
        ranked = cf.rank_remediations(
            "k", ["weak", "strong"],
            lookup_fn=_lookup(_row("weak", positive=1), _row("strong", positive=5)))
        assert ranked == ["strong", "weak"]

    def test_confidence_scales_the_evidence(self):
        ranked = cf.rank_remediations(
            "k", ["unsure", "sure"],
            lookup_fn=_lookup(_row("unsure", positive=3, confidence=0.1),
                              _row("sure", positive=3, confidence=0.95)))
        assert ranked == ["sure", "unsure"]

    def test_delta_only_breaks_ties(self):
        """A single huge delta must not outvote a consistent record."""
        ranked = cf.rank_remediations(
            "k", ["big_delta_once", "consistent"],
            lookup_fn=_lookup(_row("big_delta_once", positive=1, delta=90.0),
                              _row("consistent", positive=4, delta=1.0)))
        assert ranked == ["consistent", "big_delta_once"]

    def test_ties_preserve_the_callers_order(self):
        candidates = ["a", "b", "c"]
        assert cf.rank_remediations("k", candidates, lookup_fn=_lookup()) == candidates

    def test_evidence_for_an_uncandidate_slug_is_ignored(self):
        ranked = cf.rank_remediations(
            "k", ["a", "b"], lookup_fn=_lookup(_row("something-else", positive=9)))
        assert ranked == ["a", "b"]

    def test_exploration_is_not_frozen(self):
        """An unevidenced candidate stays selectable, never scored -inf."""
        assert cf._learned_score(None) == 0.0


class TestFailSoft:
    def test_a_raising_lookup_returns_the_candidates_unchanged(self):
        def boom(*_a, **_k):
            raise RuntimeError("db down")

        assert cf.rank_remediations("k", ["a", "b"], lookup_fn=boom) == ["a", "b"]

    def test_no_bottleneck_key_returns_the_candidates_unchanged(self):
        assert cf.rank_remediations("", ["a", "b"], lookup_fn=_lookup()) == ["a", "b"]

    @pytest.mark.parametrize("candidates", [None, [], ["", "   "]])
    def test_empty_candidates_never_raise(self, candidates):
        assert cf.rank_remediations("k", candidates, lookup_fn=_lookup()) == []

    def test_non_string_candidates_are_dropped_not_crashed_on(self):
        assert cf.rank_remediations("k", ["a", None, 7, "b"], lookup_fn=_lookup()) == ["a", "b"]

    def test_malformed_evidence_rows_score_zero(self):
        for row in (None, [], "text", {"remediation_slug": "a", "positive_count": "many"}):
            assert cf._learned_score(row) == 0.0

    def test_a_lookup_returning_junk_does_not_reorder(self):
        assert cf.rank_remediations(
            "k", ["a", "b"], lookup_fn=lambda *_a, **_k: [None, 7, {}]) == ["a", "b"]


class TestExplainRanking:
    def test_reports_score_and_evidence_in_ranked_order(self):
        rows = (_row("proven", positive=3), )
        out = cf.explain_ranking("k", ["untried", "proven"], lookup_fn=_lookup(*rows))
        assert [slug for slug, _score, _ev in out] == ["proven", "untried"]
        assert out[0][1] > out[1][1]
        assert out[0][2]["positive_count"] == 3
        assert out[1][2] is None

    def test_is_fail_soft_too(self):
        def boom(*_a, **_k):
            raise RuntimeError("db down")

        assert cf.explain_ranking("k", ["a"], lookup_fn=boom) == [("a", 0.0, None)]


class TestModuleContract:
    def test_the_learned_weight_is_fleet_tunable(self):
        """ORCH_-prefixed so fleet_control.py can push it; see CLAUDE.md."""
        assert isinstance(cf.LEARNED_WEIGHT, float)
        assert "ORCH_CAUSAL_LEARNED_WEIGHT" in open(cf.__file__).read()
