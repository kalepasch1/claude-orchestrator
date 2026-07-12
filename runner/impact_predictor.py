"""Impact prediction before queue admission.

Predicts expected impact (revenue/error-reduction/UX) + confidence for candidate
improvements. Only high-expected-value work is admitted; the rest are parked.
Feeds the economic scheduler.
"""

import os
import json
import threading
from typing import TypedDict, Optional
from dataclasses import dataclass, asdict


@dataclass
class ImpactScore:
    """Impact prediction result."""
    expected_value: float  # 0-100, composite score
    confidence: float  # 0-1, prediction confidence
    revenue_impact: float  # 0-100, estimated revenue impact
    error_reduction: float  # 0-100, estimated error reduction (0-100%)
    ux_impact: float  # 0-100, estimated UX improvement
    reasoning: str  # Human-readable explanation


@dataclass
class AdmissionDecision:
    """Queue admission decision."""
    admitted: bool
    score: ImpactScore
    reason: str  # Why admitted or parked


class ImpactPredictor:
    """Predicts and gates candidate improvements by expected impact."""

    def __init__(self):
        self._lock = threading.Lock()
        self._admission_threshold = float(os.getenv('IMPACT_ADMISSION_THRESHOLD', '60'))
        self._confidence_threshold = float(os.getenv('IMPACT_CONFIDENCE_THRESHOLD', '0.5'))
        self._min_expected_value = float(os.getenv('IMPACT_MIN_EXPECTED_VALUE', '50'))

    def score(self, candidate: dict) -> ImpactScore:
        """Score a candidate improvement.

        Args:
            candidate: dict with keys like 'title', 'description', 'category',
                      'effort_estimate', 'affected_users', 'error_rate_reduction',
                      'revenue_potential', 'ux_benefit'

        Returns:
            ImpactScore with expected_value, confidence, and component scores.
        """
        if not candidate or not isinstance(candidate, dict):
            return ImpactScore(
                expected_value=0,
                confidence=0,
                revenue_impact=0,
                error_reduction=0,
                ux_impact=0,
                reasoning="Invalid candidate format"
            )

        # Extract signals with defaults
        category = candidate.get('category', 'unknown').lower()
        effort = candidate.get('effort_estimate', 5)  # story points
        affected_users = candidate.get('affected_users', 0)
        error_reduction = candidate.get('error_rate_reduction', 0)  # percentage
        revenue_potential = candidate.get('revenue_potential', 0)  # dollars
        ux_benefit = candidate.get('ux_benefit', 'none').lower()

        # Component scoring (0-100)
        revenue_impact = self._score_revenue(revenue_potential, affected_users)
        error_impact = self._score_error_reduction(error_reduction)
        ux_impact = self._score_ux(ux_benefit, affected_users)

        # Effort adjustment: linear penalty, no cap
        effort_penalty = effort

        # Expected value: weighted sum of components minus linear effort penalty
        expected_value = (
            revenue_impact * 0.8 +
            error_impact * 1.3 +
            ux_impact * 0.5
        ) - effort_penalty

        expected_value = max(0, min(100, expected_value))

        # Confidence based on signal clarity
        signals_present = sum([
            1 if revenue_potential > 0 else 0,
            1 if error_reduction > 0 else 0,
            1 if ux_benefit != 'none' else 0,
            1 if affected_users > 0 else 0,
        ])
        confidence = 0.3 + (signals_present * 0.175)  # 0.3-1.0 based on signals

        reasoning = self._explain_score(
            category, revenue_impact, error_impact, ux_impact, effort_penalty
        )

        return ImpactScore(
            expected_value=round(expected_value, 1),
            confidence=round(confidence, 2),
            revenue_impact=round(revenue_impact, 1),
            error_reduction=round(error_impact, 1),
            ux_impact=round(ux_impact, 1),
            reasoning=reasoning
        )

    def decide(self, candidate: dict) -> AdmissionDecision:
        """Decide whether to admit a candidate to the queue.

        Args:
            candidate: Candidate improvement dict

        Returns:
            AdmissionDecision with admitted bool and reasoning
        """
        with self._lock:
            score = self.score(candidate)

            # Gate 1: Confidence threshold (prediction quality)
            if score.confidence < self._confidence_threshold:
                return AdmissionDecision(
                    admitted=False,
                    score=score,
                    reason=f"Prediction confidence {score.confidence} below threshold {self._confidence_threshold}"
                )

            # Gate 2: Admission threshold (expected value magnitude)
            if score.expected_value < self._admission_threshold:
                return AdmissionDecision(
                    admitted=False,
                    score=score,
                    reason=f"Expected value {score.expected_value} below admission threshold {self._admission_threshold}"
                )

            # Gate 3: Minimum expected value check (baseline)
            if score.expected_value < self._min_expected_value:
                return AdmissionDecision(
                    admitted=False,
                    score=score,
                    reason=f"Expected value {score.expected_value} below minimum {self._min_expected_value}"
                )

            return AdmissionDecision(
                admitted=True,
                score=score,
                reason=f"High expected value ({score.expected_value}) with confidence {score.confidence}"
            )

    def park(self, candidate: dict, reason: str) -> dict:
        """Record a parked (rejected) candidate.

        Args:
            candidate: Rejected candidate
            reason: Why it was parked

        Returns:
            Parked candidate record with metadata
        """
        return {
            'candidate': candidate,
            'decision_reason': reason,
            'timestamp': str(__import__('time').time()),
        }

    def _score_revenue(self, revenue_potential: float, affected_users: int) -> float:
        """Score revenue impact."""
        if revenue_potential <= 0:
            return 0
        # Scale to 0-100: $100k+ → 100, scales down
        return min(100, (revenue_potential / 100000) * 100)

    def _score_error_reduction(self, error_reduction_pct: float) -> float:
        """Score error reduction impact."""
        if error_reduction_pct <= 0:
            return 0
        # Direct scale: 50% error reduction → 50 points
        return min(100, error_reduction_pct)

    def _score_ux(self, ux_benefit: str, affected_users: int) -> float:
        """Score UX impact."""
        ux_tiers = {
            'transformative': 100,
            'major': 75,
            'moderate': 50,
            'minor': 25,
            'none': 0,
        }
        base = ux_tiers.get(ux_benefit, 0)
        # Boost for high user impact
        if affected_users > 10000:
            return min(100, base * 1.2)
        elif affected_users > 1000:
            return min(100, base * 1.1)
        return base

    def _explain_score(self, category: str, revenue: float, error: float, ux: float, effort: float) -> str:
        """Generate human-readable explanation."""
        components = []
        if revenue > 0:
            components.append(f"revenue +{revenue:.0f}")
        if error > 0:
            components.append(f"error-reduction +{error:.0f}")
        if ux > 0:
            components.append(f"ux +{ux:.0f}")
        if effort > 0:
            components.append(f"effort -{effort:.0f}")

        comp_str = ", ".join(components) if components else "no clear impact signals"
        return f"[{category}] {comp_str}"


# Module-level singleton
_predictor = ImpactPredictor()


def score(candidate: dict) -> ImpactScore:
    """Module-level wrapper: score a candidate."""
    return _predictor.score(candidate)


def decide(candidate: dict) -> AdmissionDecision:
    """Module-level wrapper: make admission decision."""
    return _predictor.decide(candidate)


def park(candidate: dict, reason: str) -> dict:
    """Module-level wrapper: park a rejected candidate."""
    return _predictor.park(candidate, reason)


def set_thresholds(admission: float = None, confidence: float = None, min_value: float = None):
    """Adjust admission thresholds for testing."""
    if admission is not None:
        _predictor._admission_threshold = admission
    if confidence is not None:
        _predictor._confidence_threshold = confidence
    if min_value is not None:
        _predictor._min_expected_value = min_value
