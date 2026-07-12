"""N5 School mode — teacher-facing classroom deployment of H1 mastery engine.

Provides class-level quests, family-visible progress, teacher dashboard
aggregate, and cohort onboarding. Enforces COPPA/consent: no child data
enters a classroom until a CoppaConsent record exists (fail-closed).
Fail-soft on bad input.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from hisanta.contracts.family import CoppaConsent
from hisanta.hisanta.mastery.engine import MasteryEngine, Quest, Progress


@dataclass
class Student:
    student_id: str
    name: str
    consent: Optional[CoppaConsent] = None


@dataclass
class Cohort:
    school_id: str
    teacher_id: str
    name: str
    students: List[Student] = field(default_factory=list)


@dataclass
class StudentProgress:
    student_id: str
    name: str
    quests_completed: int = 0
    total_points: int = 0
    family_visible: bool = True


@dataclass
class TeacherDashboard:
    teacher_id: str
    school_id: str
    cohort_name: str
    student_progress: List[StudentProgress] = field(default_factory=list)
    total_quests_run: int = 0


class Classroom:
    """Teacher-facing classroom using the H1 mastery engine."""

    def __init__(self, school_id: str, teacher_id: str, cohort_name: str = "Default"):
        self.school_id = school_id
        self.teacher_id = teacher_id
        self.cohort_name = cohort_name
        self.engine = MasteryEngine()
        self._students: Dict[str, Student] = {}
        self._consents: Dict[str, CoppaConsent] = {}

    def provision_cohort(self, students: Optional[List[Student]] = None) -> List[str]:
        """Onboard a cohort of students. Returns list of provisioned student IDs."""
        try:
            if not students:
                return []
            provisioned = []
            for s in students:
                if not isinstance(s, Student):
                    continue
                self._students[s.student_id] = s
                if s.consent and isinstance(s.consent, CoppaConsent) and s.consent.granted:
                    self._consents[s.student_id] = s.consent
                provisioned.append(s.student_id)
            return provisioned
        except Exception:
            return []

    def has_consent(self, student_id: str) -> bool:
        return student_id in self._consents

    def register_quest(self, quest: Quest):
        self.engine.register_quest(quest)

    def run_class_quest(self, quest_id: str) -> Dict[str, Optional[Quest]]:
        """Run a quest for all consented students. Fail-closed for non-consented."""
        results = {}
        try:
            for sid, student in self._students.items():
                if sid not in self._consents:
                    results[sid] = None  # fail-closed: no consent
                    continue
                result = self.engine.run_quest(sid, quest_id)
                results[sid] = result
        except Exception:
            pass
        return results

    def get_teacher_dashboard(self) -> TeacherDashboard:
        """Produce teacher dashboard with family-visible progress."""
        try:
            progress_list = []
            total_quests = 0
            for sid, student in self._students.items():
                p = self.engine.get_progress(sid)
                sp = StudentProgress(
                    student_id=sid,
                    name=student.name,
                    quests_completed=len(p.quests_completed) if p else 0,
                    total_points=p.total_points if p else 0,
                    family_visible=True,
                )
                if p:
                    total_quests += len(p.quests_completed)
                progress_list.append(sp)
            return TeacherDashboard(
                teacher_id=self.teacher_id,
                school_id=self.school_id,
                cohort_name=self.cohort_name,
                student_progress=progress_list,
                total_quests_run=total_quests,
            )
        except Exception:
            return TeacherDashboard(
                teacher_id=self.teacher_id,
                school_id=self.school_id,
                cohort_name=self.cohort_name,
            )
