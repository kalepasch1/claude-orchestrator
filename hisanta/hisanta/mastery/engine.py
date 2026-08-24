"""H1 Mastery Engine - quest execution and progress tracking."""
from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict, Sequence
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
# Same import spelling as gifting.protocol and kindness.mint so every module in
# the stack lands on the ONE canonical contracts module, not a second copy.
from hisanta.contracts.family import MasteryEfficacyMetric, RewardSchedule

#: A quest is "done" for scheduling purposes when it says so. Both the local
#: Quest below and contracts.family.Quest expose `.completed`, so the review /
#: weekly helpers accept either without caring which one it got.
MAX_DIFFICULTY = 10
MIN_DIFFICULTY = 1
#: Review interval growth on a successful recall (SM-2 style, deliberately
#: gentle: 2.5x, floored at 1 day so a quest never falls out of rotation).
REVIEW_GROWTH = 2.5
#: An average above this raises difficulty; below the lower bound drops it.
#: Exactly on a boundary changes nothing — a single boundary score is noise.
DIFFICULTY_UP_ABOVE = 0.8
DIFFICULTY_DOWN_BELOW = 0.4


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

    # ── Spaced repetition ────────────────────────────────────────────────────

    def schedule_review(self, quest: Any, last_interval: int, success: bool) -> int:
        """Days until this quest should come round again.

        Success stretches the interval by REVIEW_GROWTH; a miss resets it to 1.
        The floor of 1 also absorbs a zero or negative `last_interval`, so a
        bad caller cannot schedule a review in the past or never.
        """
        if not success:
            return 1
        return max(1, int(last_interval * REVIEW_GROWTH))

    def adaptive_difficulty(self, current: int, recent_scores: Sequence[float]) -> int:
        """Nudge difficulty one step from recent performance.

        No scores means no evidence, so difficulty is unchanged — never guess
        a child up or down from an empty history. Moves one step at a time and
        clamps to [MIN_DIFFICULTY, MAX_DIFFICULTY].
        """
        if not recent_scores:
            return current
        average = sum(recent_scores) / len(recent_scores)
        if average > DIFFICULTY_UP_ABOVE:
            return min(MAX_DIFFICULTY, current + 1)
        if average < DIFFICULTY_DOWN_BELOW:
            return max(MIN_DIFFICULTY, current - 1)
        return current

    def complete_weekly_quests(self, quests: Sequence[Any]) -> Dict[str, Any]:
        """Open at most ONE advent door for a fully-completed week.

        Exactly one, however many quests were finished: the door is the weekly
        reward, and letting a big week open several doors turns a fixed
        schedule into a variable-ratio one, which is the pattern the
        constitution forbids. An empty week opens nothing.
        """
        all_complete = bool(quests) and all(getattr(q, "completed", False) for q in quests)
        return {
            "advent_door_opened": all_complete,
            "doors_opened": 1 if all_complete else 0,
            "quests_considered": len(quests),
        }

    def create_reward_schedule(
        self, schedule_type: str, coupled_to_purchase: bool = False
    ) -> Optional[RewardSchedule]:
        """Build a reward schedule, refusing the loot-box combination.

        A variable-ratio schedule coupled to a purchase is the loot box: it is
        rejected outright (None) rather than created-and-flagged, so no caller
        can build one and then decide to use it anyway. The flag is meaningless
        for any other schedule type and is stored as False there.
        """
        is_variable_ratio = schedule_type == "variable_ratio"
        if is_variable_ratio and coupled_to_purchase:
            return None
        return RewardSchedule(
            schedule_type=schedule_type,
            variable_ratio_coupled_to_purchase=False,
        )

    def get_efficacy_metrics(
        self, subject: str, scores: Sequence[float]
    ) -> MasteryEfficacyMetric:
        """Mean score and attempt count for one subject.

        No attempts reports 0.0 rather than raising or reporting a fabricated
        score — "we have not measured this yet" must be readable as such.
        """
        attempts = len(scores)
        mean = sum(scores) / attempts if attempts else 0.0
        return MasteryEfficacyMetric(subject=subject, score=mean, attempts=attempts)
