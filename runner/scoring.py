"""
Impact scoring and task admission for the economic scheduler.

Scores improvements on expected impact (revenue/error-reduction/UX) and confidence.
High-expected-value work is admitted; rest are parked.
"""

import dataclasses
import enum
from typing import Optional


class ImpactDimension(enum.Enum):
    """Impact categories."""
    REVENUE = "revenue"
    ERROR_REDUCTION = "error_reduction"
    UX = "ux"


@dataclasses.dataclass
class Impact:
    """Single impact dimension: value and confidence [0-1]."""
    dimension: ImpactDimension
    value: float  # Magnitude: dollars, error-reduction %, UX percentile
    confidence: float = 1.0  # [0-1]

    def expected_value(self) -> float:
        """value * confidence."""
        return self.value * self.confidence


@dataclasses.dataclass
class TaskScore:
    """Scored task with admission decision."""
    task_id: str
    impacts: list[Impact]
    total_expected_value: float
    admitted: bool
    reason: str

    @classmethod
    def score(
        cls,
        task_id: str,
        impacts: list[Impact],
        threshold: float = 10.0,  # Min expected value to admit
    ) -> "TaskScore":
        """Score a task and decide admission."""
        total = sum(i.expected_value() for i in impacts)
        admitted = total >= threshold
        reason = (
            f"Total EV={total:.1f}, threshold={threshold}"
            if admitted
            else f"Total EV={total:.1f} < threshold={threshold} (parked)"
        )
        return cls(
            task_id=task_id,
            impacts=impacts,
            total_expected_value=total,
            admitted=admitted,
            reason=reason,
        )


def score_task(
    task_id: str,
    impacts: list[Impact],
    threshold: float = 10.0,
) -> TaskScore:
    """Score and admit/park a task. Returns TaskScore with decision."""
    return TaskScore.score(task_id, impacts, threshold)
