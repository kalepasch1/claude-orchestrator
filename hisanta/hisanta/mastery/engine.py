"""Mastery engine with spaced-repetition, adaptive difficulty, and reward scheduling."""

from __future__ import annotations

from hisanta.contracts.family import (
    ConstitutionVerdict,
    MasteryEfficacyMetric,
    Quest,
    RewardSchedule,
    constitution_check,
)


class MasteryEngine:
    """Engine for mastery-based learning progression."""

    def __init__(self) -> None:
        self._history: list[dict] = []

    def schedule_review(
        self, quest: Quest, last_interval: int = 1, success: bool = True
    ) -> int:
        """Spaced-repetition scheduler.

        If success, multiply interval by 2.5 (min 1).
        If fail, reset to 1.
        Returns next interval in days.
        """
        try:
            if not isinstance(last_interval, (int, float)) or last_interval < 1:
                last_interval = 1
            if success:
                return max(1, int(last_interval * 2.5))
            return 1
        except Exception:
            return 1

    def adaptive_difficulty(
        self, current_level: int, recent_scores: list[float]
    ) -> int:
        """Adjust difficulty based on recent performance.

        If avg > 0.8 increase, if avg < 0.4 decrease, else keep. Clamp 1-10.
        """
        try:
            if not isinstance(current_level, (int, float)):
                current_level = 1
            current_level = int(current_level)
            if not recent_scores:
                return max(1, min(10, current_level))
            avg = sum(recent_scores) / len(recent_scores)
            if avg > 0.8:
                current_level += 1
            elif avg < 0.4:
                current_level -= 1
            return max(1, min(10, current_level))
        except Exception:
            return max(1, min(10, current_level if isinstance(current_level, int) else 1))

    def complete_weekly_quests(self, quests: list[Quest]) -> dict:
        """Check weekly quest completion. Opens exactly one advent door if all complete."""
        try:
            if not quests:
                return {"advent_door_opened": False, "doors_opened": 0}
            all_done = all(q.completed for q in quests)
            if all_done:
                return {"advent_door_opened": True, "doors_opened": 1}
            return {"advent_door_opened": False, "doors_opened": 0}
        except Exception:
            return {"advent_door_opened": False, "doors_opened": 0}

    def create_reward_schedule(
        self,
        schedule_type: str = "fixed",
        coupled_to_purchase: bool = False,
    ) -> RewardSchedule | None:
        """Create a reward schedule.

        Refuses (returns None) if coupled_to_purchase is True AND
        schedule_type contains 'variable_ratio'.
        """
        try:
            if coupled_to_purchase and "variable_ratio" in schedule_type:
                verdict = constitution_check("charge_child")
                if verdict == ConstitutionVerdict.DENY:
                    return None
            return RewardSchedule(
                schedule_type=schedule_type,
                variable_ratio_coupled_to_purchase=coupled_to_purchase,
            )
        except Exception:
            return RewardSchedule()

    def get_efficacy_metrics(
        self, subject: str, scores: list[float]
    ) -> MasteryEfficacyMetric:
        """Compute efficacy metrics for a subject."""
        try:
            if not scores:
                return MasteryEfficacyMetric(subject=subject or "")
            avg_score = sum(scores) / len(scores)
            return MasteryEfficacyMetric(
                subject=subject or "",
                score=round(avg_score, 4),
                attempts=len(scores),
            )
        except Exception:
            return MasteryEfficacyMetric(subject=subject or "")
