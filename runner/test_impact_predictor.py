"""Tests for impact prediction and queue admission."""

import pytest
import impact_predictor as imp


class TestScoring:
    """Test impact scoring logic."""

    def test_score_high_value_candidate(self):
        """High revenue + low effort = high expected value."""
        candidate = {
            'title': 'Add revenue tracking',
            'category': 'revenue',
            'effort_estimate': 2,
            'affected_users': 50000,
            'revenue_potential': 250000,
            'error_rate_reduction': 0,
            'ux_benefit': 'none',
        }
        score = imp.score(candidate)
        assert score.expected_value > 70
        assert score.confidence >= 0.5
        assert score.revenue_impact > 50

    def test_score_error_reduction_focus(self):
        """High error reduction = high score."""
        candidate = {
            'title': 'Fix memory leak',
            'category': 'reliability',
            'effort_estimate': 3,
            'affected_users': 100000,
            'revenue_potential': 0,
            'error_rate_reduction': 45,
            'ux_benefit': 'none',
        }
        score = imp.score(candidate)
        assert score.expected_value > 50
        assert score.error_reduction > 40

    def test_score_ux_improvement(self):
        """Major UX benefit drives score."""
        candidate = {
            'title': 'Dark mode',
            'category': 'ux',
            'effort_estimate': 4,
            'affected_users': 80000,
            'revenue_potential': 0,
            'error_rate_reduction': 0,
            'ux_benefit': 'major',
        }
        score = imp.score(candidate)
        assert score.expected_value > 40
        assert score.ux_impact >= 75

    def test_score_low_effort_boost(self):
        """Low effort amplifies expected value."""
        low_effort = {
            'title': 'Quick fix',
            'category': 'bug',
            'effort_estimate': 1,
            'affected_users': 1000,
            'revenue_potential': 50000,
            'error_rate_reduction': 10,
            'ux_benefit': 'minor',
        }
        score_low = imp.score(low_effort)

        high_effort = {
            'title': 'Big rewrite',
            'category': 'bug',
            'effort_estimate': 8,
            'affected_users': 1000,
            'revenue_potential': 50000,
            'error_rate_reduction': 10,
            'ux_benefit': 'minor',
        }
        score_high = imp.score(high_effort)

        assert score_low.expected_value > score_high.expected_value

    def test_score_no_signals(self):
        """Candidate with no impact signals scores low."""
        candidate = {
            'title': 'Cleanup',
            'category': 'refactor',
            'effort_estimate': 5,
            'affected_users': 0,
            'revenue_potential': 0,
            'error_rate_reduction': 0,
            'ux_benefit': 'none',
        }
        score = imp.score(candidate)
        assert score.expected_value < 30
        assert score.confidence < 0.5

    def test_score_invalid_candidate(self):
        """Invalid input returns zero score."""
        assert imp.score(None).expected_value == 0
        assert imp.score({}).expected_value == 0
        assert imp.score('not a dict').expected_value == 0

    def test_score_multiple_signals(self):
        """Multiple impact signals increase confidence."""
        weak_signals = {
            'title': 'Test',
            'effort_estimate': 2,
            'revenue_potential': 10000,
        }
        score_weak = imp.score(weak_signals)

        strong_signals = {
            'title': 'Test',
            'effort_estimate': 2,
            'revenue_potential': 10000,
            'affected_users': 5000,
            'error_rate_reduction': 5,
            'ux_benefit': 'minor',
        }
        score_strong = imp.score(strong_signals)

        assert score_strong.confidence > score_weak.confidence

    def test_ux_boost_for_high_user_count(self):
        """UX impact scales with affected user count."""
        low_users = {
            'title': 'UX',
            'effort_estimate': 2,
            'ux_benefit': 'major',
            'affected_users': 100,
        }
        score_low = imp.score(low_users)

        high_users = {
            'title': 'UX',
            'effort_estimate': 2,
            'ux_benefit': 'major',
            'affected_users': 50000,
        }
        score_high = imp.score(high_users)

        assert score_high.ux_impact > score_low.ux_impact

    def test_score_has_reasoning(self):
        """Score includes human-readable explanation."""
        candidate = {
            'title': 'API optimization',
            'category': 'performance',
            'effort_estimate': 3,
            'revenue_potential': 100000,
            'error_rate_reduction': 20,
            'ux_benefit': 'moderate',
        }
        score = imp.score(candidate)
        assert 'performance' in score.reasoning.lower()
        assert len(score.reasoning) > 10


class TestAdmission:
    """Test queue admission gating."""

    def setup_method(self):
        """Reset thresholds before each test."""
        imp.set_thresholds(admission=60, confidence=0.5, min_value=50)

    def test_admit_high_value(self):
        """High-value candidate is admitted."""
        candidate = {
            'title': 'Revenue feature',
            'effort_estimate': 2,
            'revenue_potential': 500000,
            'affected_users': 100000,
        }
        decision = imp.decide(candidate)
        assert decision.admitted is True
        assert 'High expected value' in decision.reason

    def test_park_low_expected_value(self):
        """Low expected value is parked."""
        candidate = {
            'title': 'Niche fix',
            'effort_estimate': 10,
            'revenue_potential': 0,
            'affected_users': 10,
            'error_rate_reduction': 1,
        }
        decision = imp.decide(candidate)
        assert decision.admitted is False
        assert 'minimum' in decision.reason or 'threshold' in decision.reason

    def test_park_low_confidence(self):
        """Low confidence blocks admission even with high score."""
        imp.set_thresholds(confidence=0.95)
        candidate = {
            'title': 'Speculative feature',
            'effort_estimate': 2,
            'revenue_potential': 50000,
        }
        decision = imp.decide(candidate)
        # Low signal count = low confidence
        assert decision.admitted is False
        assert 'confidence' in decision.reason.lower()

    def test_multiple_high_signals_admitted(self):
        """Multiple strong signals → admission."""
        candidate = {
            'title': 'Comprehensive fix',
            'effort_estimate': 3,
            'revenue_potential': 200000,
            'affected_users': 50000,
            'error_rate_reduction': 30,
            'ux_benefit': 'major',
        }
        decision = imp.decide(candidate)
        assert decision.admitted is True
        assert decision.score.confidence > 0.7

    def test_admission_score_included(self):
        """Admission decision includes full score."""
        candidate = {
            'title': 'Test',
            'effort_estimate': 1,
            'revenue_potential': 100000,
        }
        decision = imp.decide(candidate)
        assert decision.score.expected_value > 0
        assert decision.score.confidence > 0
        assert isinstance(decision.score.reasoning, str)

    def test_threshold_configuration(self):
        """Thresholds can be adjusted for testing."""
        imp.set_thresholds(admission=90, min_value=85)
        candidate = {
            'title': 'Marginal feature',
            'effort_estimate': 2,
            'revenue_potential': 100000,
            'affected_users': 5000,
        }
        # Should be parked with strict thresholds
        decision = imp.decide(candidate)
        assert decision.admitted is False

        # Reset to lenient
        imp.set_thresholds(admission=30, min_value=20)
        decision = imp.decide(candidate)
        # Should be admitted with lenient thresholds
        assert decision.admitted is True


class TestParking:
    """Test parked candidate tracking."""

    def test_park_candidate(self):
        """Parked candidate is recorded with metadata."""
        candidate = {'title': 'Rejected feature', 'effort_estimate': 15}
        reason = 'Expected value too low'
        parked = imp.park(candidate, reason)

        assert parked['candidate'] == candidate
        assert parked['decision_reason'] == reason
        assert 'timestamp' in parked

    def test_park_preserves_candidate_data(self):
        """Parked record preserves full candidate info."""
        candidate = {
            'title': 'Complex feature',
            'effort_estimate': 8,
            'description': 'Detailed desc',
            'category': 'infrastructure',
        }
        parked = imp.park(candidate, 'High effort')
        assert parked['candidate']['description'] == 'Detailed desc'
        assert parked['candidate']['category'] == 'infrastructure'


class TestIntegration:
    """Integration tests for full workflow."""

    def setup_method(self):
        """Reset defaults."""
        imp.set_thresholds(admission=60, confidence=0.5, min_value=50)

    def test_workflow_high_value_candidate(self):
        """End-to-end: high-value candidate flows through admission."""
        candidate = {
            'title': 'Critical reliability fix',
            'category': 'reliability',
            'effort_estimate': 2,
            'affected_users': 100000,
            'error_rate_reduction': 50,
            'revenue_potential': 0,
            'ux_benefit': 'none',
        }

        # Score it
        score = imp.score(candidate)
        assert score.expected_value > 60
        assert score.confidence > 0.5

        # Decide admission
        decision = imp.decide(candidate)
        assert decision.admitted is True

    def test_workflow_low_value_candidate_parked(self):
        """End-to-end: low-value candidate is scored, rejected, and parked."""
        candidate = {
            'title': 'Minor cosmetic tweak',
            'category': 'ui',
            'effort_estimate': 6,
            'affected_users': 100,
            'error_rate_reduction': 0,
            'revenue_potential': 1000,
            'ux_benefit': 'minor',
        }

        # Score it
        score = imp.score(candidate)
        assert score.expected_value < 60

        # Decide admission
        decision = imp.decide(candidate)
        assert decision.admitted is False

        # Park it
        parked = imp.park(candidate, decision.reason)
        assert parked['candidate']['title'] == candidate['title']
        assert parked['decision_reason'] == decision.reason

    def test_candidate_comparison(self):
        """Candidates can be ranked by expected value."""
        candidates = [
            {
                'title': 'High value',
                'effort_estimate': 2,
                'revenue_potential': 500000,
                'affected_users': 100000,
            },
            {
                'title': 'Medium value',
                'effort_estimate': 3,
                'error_rate_reduction': 30,
                'affected_users': 50000,
            },
            {
                'title': 'Low value',
                'effort_estimate': 10,
                'revenue_potential': 5000,
            },
        ]

        scores = [imp.score(c) for c in candidates]
        ranked = sorted(scores, key=lambda s: s.expected_value, reverse=True)

        # High value should rank first
        assert ranked[0].expected_value > ranked[1].expected_value
        assert ranked[1].expected_value > ranked[2].expected_value


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
