"""Tests for N5 school mode — classroom deployment of H1 mastery engine."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hisanta.contracts.family import CoppaConsent
from hisanta.hisanta.mastery.engine import Quest
from hisanta.hisanta.school.classroom import Classroom, Student


def _make_classroom():
    c = Classroom(school_id="school1", teacher_id="teacher1", cohort_name="Grade 3")
    c.register_quest(Quest(quest_id="q1", title="Math Basics"))
    c.register_quest(Quest(quest_id="q2", title="Reading"))
    return c


def _consented_student(sid, name):
    return Student(student_id=sid, name=name,
                   consent=CoppaConsent(child_id=sid, parent_id=f"p-{sid}", school_id="school1"))


def _no_consent_student(sid, name):
    return Student(student_id=sid, name=name, consent=None)


def test_provision_cohort():
    c = _make_classroom()
    students = [_consented_student("s1", "Alice"), _consented_student("s2", "Bob")]
    ids = c.provision_cohort(students)
    assert set(ids) == {"s1", "s2"}


def test_blocks_quests_without_coppa_consent():
    c = _make_classroom()
    c.provision_cohort([
        _consented_student("s1", "Alice"),
        _no_consent_student("s2", "Bob"),
    ])
    results = c.run_class_quest("q1")
    assert results["s1"] is not None  # consented: runs
    assert results["s1"].completed
    assert results["s2"] is None      # no consent: blocked


def test_class_quest_through_engine():
    c = _make_classroom()
    c.provision_cohort([_consented_student("s1", "Alice")])
    results = c.run_class_quest("q1")
    assert results["s1"].quest_id == "q1"
    assert results["s1"].completed


def test_teacher_dashboard_with_progress():
    c = _make_classroom()
    c.provision_cohort([
        _consented_student("s1", "Alice"),
        _consented_student("s2", "Bob"),
        _no_consent_student("s3", "Charlie"),
    ])
    c.run_class_quest("q1")
    c.run_class_quest("q2")
    dashboard = c.get_teacher_dashboard()
    assert dashboard.teacher_id == "teacher1"
    assert dashboard.school_id == "school1"
    assert len(dashboard.student_progress) == 3
    # Alice and Bob ran 2 quests each; Charlie ran 0
    alice = [p for p in dashboard.student_progress if p.student_id == "s1"][0]
    assert alice.quests_completed == 2
    assert alice.family_visible
    charlie = [p for p in dashboard.student_progress if p.student_id == "s3"][0]
    assert charlie.quests_completed == 0


def test_end_to_end_classroom():
    """Full e2e: provision cohort, block non-consented, run quests, dashboard."""
    c = _make_classroom()
    c.provision_cohort([
        _consented_student("s1", "Alice"),
        _no_consent_student("s2", "Bob"),
    ])
    results = c.run_class_quest("q1")
    assert results["s1"] is not None
    assert results["s2"] is None
    dashboard = c.get_teacher_dashboard()
    assert dashboard.total_quests_run >= 1
    assert any(p.family_visible for p in dashboard.student_progress)
