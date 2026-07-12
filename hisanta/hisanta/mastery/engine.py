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
