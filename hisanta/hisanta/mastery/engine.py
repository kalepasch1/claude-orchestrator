"""H1 Mastery Engine - quest execution and progress tracking."""
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class Quest:
    quest_id: str
    title: str
    description: str = ""
    difficulty: int = 1
    completed: bool = False


@dataclass
class Progress:
    student_id: str
    quests_completed: List[str] = field(default_factory=list)
    total_points: int = 0

    def record(self, quest_id: str, points: int = 10):
        if quest_id not in self.quests_completed:
            self.quests_completed.append(quest_id)
            self.total_points += points


class MasteryEngine:
    """Core mastery engine for quest execution."""

    def __init__(self):
        self._quests: Dict[str, Quest] = {}
        self._progress: Dict[str, Progress] = {}

    def register_quest(self, quest: Quest):
        self._quests[quest.quest_id] = quest

    def run_quest(self, student_id: str, quest_id: str) -> Optional[Quest]:
        """Run a quest for a student. Returns completed quest or None."""
        quest = self._quests.get(quest_id)
        if not quest:
            return None
        if student_id not in self._progress:
            self._progress[student_id] = Progress(student_id=student_id)
        progress = self._progress[student_id]
        progress.record(quest_id)
        quest_copy = Quest(
            quest_id=quest.quest_id,
            title=quest.title,
            description=quest.description,
            difficulty=quest.difficulty,
            completed=True,
        )
        return quest_copy

    def get_progress(self, student_id: str) -> Optional[Progress]:
        return self._progress.get(student_id)

    def get_all_progress(self) -> Dict[str, Progress]:
        return dict(self._progress)

    # --- H1 spaced repetition / adaptive difficulty -----------------------
    # These operate on hisanta.contracts.family.Quest (the domain contract),
    # which is a different type from the local execution-record Quest above.
    # Neither is annotated here so the two can coexist without collision.

    def schedule_review(self, quest, last_interval: int = 1, success: bool = True) -> int:
        """Next review interval in days. Success expands 2.5x, failure resets to 1.

        A failed recall means the item is not learned, so the interval collapses
        rather than decaying — the whole point of spaced repetition.
        """
        try:
            if not success:
                return 1
            return max(1, int(max(1, int(last_interval)) * 2.5))
        except Exception:
            return 1

    def adaptive_difficulty(self, current: int, recent_scores) -> int:
        """Nudge difficulty by one step on sustained success/struggle. Clamped 1..10.

        Boundaries are strict (>0.8 up, <0.4 down) so a learner sitting exactly on
        the threshold is left where they are instead of oscillating.
        """
        try:
            level = int(current)
            scores = [float(s) for s in (recent_scores or [])]
            if not scores:
                return max(1, min(10, level))
            average = sum(scores) / len(scores)
            if average > 0.8:
                level += 1
            elif average < 0.4:
                level -= 1
            return max(1, min(10, level))
        except Exception:
            try:
                return max(1, min(10, int(current)))
            except Exception:
                return 1

    def complete_weekly_quests(self, quests) -> Dict:
        """Open at most ONE advent door per week, and only if every quest is done.

        One door regardless of how many quests were completed: the reward is for
        finishing the week, not for volume, so there is nothing to farm.
        """
        try:
            items = list(quests or [])
            all_done = bool(items) and all(getattr(q, "completed", False) for q in items)
            return {"advent_door_opened": all_done, "doors_opened": 1 if all_done else 0}
        except Exception:
            return {"advent_door_opened": False, "doors_opened": 0}

    def create_reward_schedule(self, schedule_type: str = "fixed",
                               coupled_to_purchase: bool = False):
        """Build a RewardSchedule, refusing variable-ratio coupled to purchase.

        Variable-ratio reinforcement tied to spending is the slot-machine pattern.
        It is refused outright (returns None) rather than merely discouraged.
        """
        try:
            from hisanta.contracts.family import RewardSchedule as _RewardSchedule
            if schedule_type == "variable_ratio" and coupled_to_purchase:
                return None
            return _RewardSchedule(
                schedule_type=schedule_type,
                variable_ratio_coupled_to_purchase=(
                    schedule_type == "variable_ratio" and coupled_to_purchase),
            )
        except Exception:
            return None

    def get_efficacy_metrics(self, subject: str, scores):
        """Mean score and attempt count for a subject."""
        from hisanta.contracts.family import MasteryEfficacyMetric
        try:
            values = [float(s) for s in (scores or [])]
            if not values:
                return MasteryEfficacyMetric(subject=subject, score=0.0, attempts=0)
            return MasteryEfficacyMetric(
                subject=subject,
                score=sum(values) / len(values),
                attempts=len(values),
            )
        except Exception:
            return MasteryEfficacyMetric(subject=subject, score=0.0, attempts=0)
