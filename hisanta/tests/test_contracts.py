"""Tests for hisanta.contracts.family module."""

import pytest
from hisanta.contracts.family import (
    ClassroomCohort,
    ConstitutionVerdict,
    CoppaConsent,
    GiftLane,
    GrandmaStorySlot,
    MatchJar,
    MasteryEfficacyMetric,
    MilestoneReaction,
    ParentApproval,
    ParentVerificationReceipt,
    PII_FREE_FIELDS,
    Quest,
    QuestKind,
    RewardCoin,
    RewardSchedule,
    SchoolQuest,
    constitution_check,
)


# --- Import checks ---

def test_module_imports():
    """All key names are importable."""
    import hisanta.contracts.family as mod
    assert hasattr(mod, "QuestKind")
    assert hasattr(mod, "Quest")
    assert hasattr(mod, "RewardSchedule")
    assert hasattr(mod, "constitution_check")


# --- Enum members ---

def test_quest_kind_members():
    assert set(QuestKind.__members__) == {"READING", "MATH", "KINDNESS"}


def test_constitution_verdict_members():
    assert set(ConstitutionVerdict.__members__) == {"ALLOW", "DENY", "ESCALATE"}


def test_gift_lane_members():
    assert set(GiftLane.__members__) == {"AD_HOC", "ADVENT", "EARNED_REWARD"}


# --- RewardSchedule defaults ---

def test_reward_schedule_default_type():
    rs = RewardSchedule()
    assert rs.schedule_type == "fixed"


def test_reward_schedule_variable_ratio_default_false():
    rs = RewardSchedule()
    assert rs.variable_ratio_coupled_to_purchase is False


def test_reward_schedule_explicit_true():
    rs = RewardSchedule(variable_ratio_coupled_to_purchase=True)
    assert rs.variable_ratio_coupled_to_purchase is True


# --- constitution_check ---

def test_constitution_check_callable():
    assert callable(constitution_check)


def test_constitution_deny_charge_child():
    assert constitution_check("charge_child") == ConstitutionVerdict.DENY


def test_constitution_deny_open_ended_child_chat():
    assert constitution_check("open_ended_child_chat") == ConstitutionVerdict.DENY


def test_constitution_escalate_loot():
    assert constitution_check("loot") == ConstitutionVerdict.ESCALATE


def test_constitution_escalate_gift():
    assert constitution_check("gift") == ConstitutionVerdict.ESCALATE


def test_constitution_escalate_ai_message():
    assert constitution_check("ai_message") == ConstitutionVerdict.ESCALATE


def test_constitution_allow_safe_action():
    assert constitution_check("view_story") == ConstitutionVerdict.ALLOW


def test_constitution_allow_empty_string():
    assert constitution_check("") == ConstitutionVerdict.ALLOW


# --- Dataclass creation ---

def test_quest_creation():
    q = Quest(kind=QuestKind.READING, description="Read a book")
    assert q.kind == QuestKind.READING
    assert q.completed is False


def test_mastery_efficacy_metric_defaults():
    m = MasteryEfficacyMetric(subject="math")
    assert m.score == 0.0
    assert m.attempts == 0


def test_grandma_story_slot_defaults():
    s = GrandmaStorySlot(story_id="s1")
    assert s.duration_seconds == 120
    assert s.recorded is False


def test_milestone_reaction_pii_field():
    r = MilestoneReaction(milestone_id="m1", reaction_text="Great!")
    assert r.child_name == ""
    assert r.approved is False


def test_pii_free_fields_is_frozenset():
    assert isinstance(PII_FREE_FIELDS, frozenset)
    assert "child_name" not in PII_FREE_FIELDS
    assert "milestone_id" in PII_FREE_FIELDS


def test_match_jar_defaults():
    mj = MatchJar()
    assert mj.balance == 0.0
    assert mj.lane == GiftLane.AD_HOC


def test_parent_approval_defaults():
    pa = ParentApproval()
    assert pa.approved is False


def test_reward_coin_defaults():
    rc = RewardCoin()
    assert rc.amount == 1
    assert rc.receipt is None


def test_parent_verification_receipt():
    pvr = ParentVerificationReceipt(verified=True, parent_id="p1")
    assert pvr.verified is True


def test_school_quest_defaults():
    sq = SchoolQuest()
    assert sq.quest is None
    assert sq.classroom == ""


def test_classroom_cohort():
    cc = ClassroomCohort(name="Alpha")
    assert cc.name == "Alpha"
    assert cc.members == []


def test_coppa_consent_defaults():
    cc = CoppaConsent()
    assert cc.consented is False
    assert cc.parent_id == ""
